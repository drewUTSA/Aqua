"""Durable challenge replay, shared budgets, storage bounds and recovery."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib

import pytest

from auth.config import AuthDenied, AuthLimited, AuthPolicy, load_auth_policy
from auth.store import IdentityStore
from nl2sql.config import Settings
from storage.pool import Storage
from test_identity_store import IDENTITY, SETTINGS, login, service, token


def test_parallel_challenge_consume_allows_exactly_one_transition(storage):
    other = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )
    stores = [IdentityStore(storage), IdentityStore(other)]
    secret, binding = token(), token()
    stores[0].issue_challenge(secret, binding, "fixture-peer")

    def consume(index):
        try:
            stores[index].consume_challenge(secret, binding)
            return "accepted"
        except AuthDenied:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as threads:
            assert sorted(threads.map(consume, range(2))) == ["accepted", "denied"]
        with pytest.raises(AuthDenied):
            IdentityStore(storage).consume_challenge(secret, binding)
    finally:
        other.close()


@pytest.mark.parametrize("change", ["binding", "expired", "purpose"])
def test_wrong_binding_expired_and_wrong_purpose_challenges_fail(storage, change):
    store = IdentityStore(storage)
    secret, binding = token(), token()
    store.issue_challenge(secret, binding, "fixture-peer")
    with storage.transaction() as conn:
        if change == "expired":
            conn.execute(
                "UPDATE app.auth_challenges SET created_at=now()-interval '2 hours',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
                (secret,),
            )
        elif change == "purpose":
            conn.execute(
                "UPDATE app.auth_challenges SET purpose='password_reset' WHERE secret_digest=%s",
                (secret,),
            )
    with pytest.raises(AuthDenied):
        store.consume_challenge(secret, token() if change == "binding" else binding)
    if change == "binding":
        store.consume_challenge(secret, binding)


@pytest.mark.parametrize("dimension", ["peer", "global"])
def test_callback_budgets_precede_provider_work_and_survive_store_restart(
    storage, dimension
):
    policy = replace(
        AuthPolicy(),
        login_peer_limit=1 if dimension == "peer" else 10,
        login_global_limit=1 if dimension == "global" else 10,
    )
    calls = []
    for index in range(2):
        store = IdentityStore(storage, policy)
        try:
            store.reserve_login(
                "same-peer" if dimension == "peer" else f"rotated-peer-{index}"
            )
            calls.append("fake verifier")
        except AuthLimited as error:
            assert 1 <= error.retry_after <= 60
    assert calls == ["fake verifier"]
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT hits FROM app.auth_admission WHERE scope='login:global'"
        ).fetchone() == (1,)


def test_account_budget_survives_logout_new_tokens_and_changed_peer(storage):
    policy = replace(service(storage).policy, login_account_limit=1)
    store = IdentityStore(storage, policy)
    secret, _, session = login(store)
    store.revoke(secret)
    with pytest.raises(AuthLimited):
        IdentityStore(storage, policy).login(
            IDENTITY, token(), token(), "changed-peer", SETTINGS
        )
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s AND revoked_at IS NULL",
            (session.user["id"],),
        ).fetchone() == (0,)
        conn.execute(
            "UPDATE app.auth_admission SET expires_at=clock_timestamp()-interval '1 second'"
        )
    assert login(store)[2].user["id"] == session.user["id"]


def test_challenge_limit_rejects_before_insert_and_recovers_after_window(storage):
    policy = replace(AuthPolicy(), challenge_peer_limit=1)
    store = IdentityStore(storage, policy)
    store.issue_challenge(token(), token(), "peer")
    with pytest.raises(AuthLimited):
        IdentityStore(storage, policy).issue_challenge(token(), token(), "peer")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.auth_challenges").fetchone() == (
            1,
        )
        conn.execute(
            "UPDATE app.auth_admission SET expires_at=clock_timestamp()-interval '1 second'"
        )
    store.issue_challenge(token(), token(), "peer")


def test_key_cardinality_denies_without_evicting_active_budget(storage):
    policy = replace(AuthPolicy(), max_admission_keys=8, login_global_limit=100)
    store = IdentityStore(storage, policy)
    for index in range(7):
        store.reserve_login(f"peer-{index}")
    with pytest.raises(AuthLimited):
        store.reserve_login("new-peer-over-cap")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.auth_admission").fetchone() == (
            8,
        )
        assert conn.execute(
            "SELECT hits FROM app.auth_admission WHERE scope='login:global'"
        ).fetchone() == (7,)


def test_parallel_shared_global_budget_admits_exactly_two_across_instances(storage):
    other = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )
    policy = replace(AuthPolicy(), login_global_limit=2)
    stores = [IdentityStore(storage, policy), IdentityStore(other, policy)]

    def reserve(index):
        try:
            stores[index % 2].reserve_login(f"fixture-peer-{index}")
            return True
        except AuthLimited:
            return False

    try:
        # Exercise atomic DB admission with ready leases. The deliberately tiny
        # cold fixture pool has its own separate overload/503 regression.
        storage.readiness()
        other.readiness()
        with ThreadPoolExecutor(max_workers=4) as threads:
            assert sum(threads.map(reserve, range(4))) == 2
    finally:
        other.close()


def test_cleanup_batch_is_bounded_and_preserves_unexpired_replay_tombstone(storage):
    store = IdentityStore(storage, replace(AuthPolicy(), cleanup_batch=2))
    retained, binding = token(), token()
    store.issue_challenge(retained, binding, "fixture-peer")
    store.consume_challenge(retained, binding)
    with storage.transaction() as conn:
        for index in range(5):
            conn.execute(
                "INSERT INTO app.auth_challenges(purpose,secret_digest,created_at,expires_at) VALUES ('google_login',%s,now()-interval '2 hours',now()-interval '1 second')",
                (hashlib.sha256(str(index).encode()).digest(),),
            )
    store.issue_challenge(token(), token(), "fixture-peer")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE expires_at<clock_timestamp()"
        ).fetchone() == (3,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE secret_digest=%s",
            (retained,),
        ).fetchone() == (True,)


@pytest.mark.parametrize(
    "field,value",
    [
        ("max_sessions", 0),
        ("max_sessions", 21),
        ("idle_seconds", 59),
        ("idle_seconds", 3601),
        ("window_seconds", 0),
        ("challenge_peer_limit", 301),
        ("max_admission_keys", 4097),
    ],
)
def test_operator_limits_are_bounded(field, value):
    with pytest.raises(ValueError, match="authentication_policy_invalid"):
        AuthPolicy(**{field: value})


def test_google_config_is_not_part_of_storage_auth_policy():
    policy = load_auth_policy(Settings(), {})
    assert policy.dataset_key == "" and policy.max_sessions == 5
    assert policy.idle_seconds == 1800
    with pytest.raises(ValueError, match="authentication_configuration_invalid"):
        load_auth_policy(Settings(), {"AUTH_MAX_SESSIONS": "unbounded"})
