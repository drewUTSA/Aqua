"""Shared admission, replay races, memory isolation and post-failure recovery."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import uuid

import pytest

from auth.config import AuthDenied, AuthLimited
from auth.password_hash import PasswordHasher
from auth.password_limits import hash_slot
from password_core_helpers import (
    EMAIL,
    NEW_PASSWORD,
    PASSWORD,
    SETTINGS,
    email_token,
    login,
    register,
    service,
)
from storage.pool import Storage


def test_known_and_unknown_mail_capacity_fail_identically_without_partial_ticket(
    storage,
):
    from auth.mailconfig import MailUnavailable

    store = service(storage)
    register(store)
    store.request_email("fills-queue@example.invalid", "verify_email", "fixture")
    store.mail_policy = replace(store.mail_policy, max_rows=1, max_pending=1)
    for address in (EMAIL, "unknown@example.invalid"):
        with pytest.raises(MailUnavailable, match="account_mail_capacity"):
            store.request_email(address, "password_reset", "fixture")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE purpose='password_reset'"
        ).fetchone() == (0,)


def test_address_budget_survives_cookie_peer_store_rotation_and_recovers(storage):
    store = service(storage, login_address_limit=2)
    register(store)
    for _ in range(2):
        with pytest.raises(AuthDenied):
            login(store, password=NEW_PASSWORD)
    other = service(storage, login_address_limit=2)
    with pytest.raises(AuthLimited):
        other.login(
            EMAIL.upper(),
            PASSWORD,
            uuid.uuid4().bytes * 2,
            uuid.uuid4().bytes * 2,
            "rotated-peer",
            SETTINGS,
        )
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.password_admission SET expires_at=now()-interval '1 second'"
        )
    assert login(other)[1].user["email"] == EMAIL


def test_global_budget_bounds_random_address_cardinality_and_no_hash_before_limit(
    storage,
):
    store = service(storage, login_global_limit=2)
    seen = []

    class Counter(PasswordHasher):
        def verify(self, password, encoded):
            seen.append("verify")
            return super().verify(password, encoded)

    store.hasher = Counter()
    for index in range(2):
        with pytest.raises(AuthDenied):
            login(store, email=f"absent{index}@example.invalid")
    with pytest.raises(AuthLimited):
        login(store, email="absent3@example.invalid")
    assert len(seen) == 2
    with storage.transaction() as conn:
        assert (
            conn.execute("SELECT count(*) FROM app.password_admission").fetchone()[0]
            <= 5
        )


def test_retained_hash_slots_fail_closed_and_operator_recovery_does_not_lose_accounts(
    storage,
):
    store = service(storage)
    owner, _ = register(store)
    with storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.password_hash_slots(id,started_at) VALUES (%s,now()-interval '2 days'),(%s,now()-interval '2 days')",
            (uuid.uuid4(), uuid.uuid4()),
        )
    # A timer cannot prove a paused process is no longer using its hash memory.
    with pytest.raises(AuthLimited):
        login(store)
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (2,)
        # Isolated operator recovery only. Live recovery must first stop every
        # auth process, as specified by the P04 operations runbook.
        conn.execute("DELETE FROM app.password_hash_slots")
    assert login(store)[1].user["id"] == owner


def test_hash_exception_releases_its_slot_and_allows_next_login(storage):
    store = service(storage)
    register(store)

    class Failing(PasswordHasher):
        def verify(self, password, encoded):
            raise RuntimeError("synthetic hash failure")

    store.hasher = Failing()
    with pytest.raises(RuntimeError, match="synthetic hash failure"):
        login(store)
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
    store.hasher = PasswordHasher()
    assert login(store)[1].user["email"] == EMAIL


def test_shared_hash_concurrency_caps_across_store_objects_without_holding_pool(
    storage,
):
    policy = service(storage).policy
    with hash_slot(storage, policy):
        with hash_slot(storage, policy):
            with storage.transaction() as conn:
                assert conn.execute(
                    "SELECT count(*) FROM app.password_hash_slots"
                ).fetchone() == (2,)
            with pytest.raises(AuthLimited):
                with hash_slot(storage, policy):
                    pytest.fail("third hash job admitted")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)


@pytest.mark.parametrize("operation", ["verify", "reset"])
def test_parallel_consumption_is_exactly_once_across_connections(storage, operation):
    other = Storage(
        replace(storage.settings, max_connections=2, max_waiting=8, wait_seconds=2)
    )
    stores = [service(other), service(other)]
    try:
        if operation == "verify":
            stores[0].request_email(EMAIL, "verify_email", "fixture")
            token = email_token(other, "verify_email")
        else:
            register(stores[0])
            stores[0].request_email(EMAIL, "password_reset", "fixture")
            token = email_token(other, "reset_password")

        def attempt(index):
            try:
                method = (
                    stores[index].complete_verification
                    if operation == "verify"
                    else stores[index].reset_password
                )
                method(token, PASSWORD if index == 0 else NEW_PASSWORD, "fixture")
                return "accepted"
            except AuthDenied:
                return "denied"

        with ThreadPoolExecutor(max_workers=2) as threads:
            assert sorted(threads.map(attempt, range(2))) == ["accepted", "denied"]
        with other.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (1,)
            assert conn.execute(
                "SELECT count(*) FROM app.password_credentials"
            ).fetchone() == (1,)
    finally:
        other.close()


def test_reset_during_detached_password_check_cannot_mint_a_stale_session(storage):
    store = service(storage)
    register(store)
    store.request_email(EMAIL, "password_reset", "fixture")
    token = email_token(storage, "reset_password")

    class RacingHasher(PasswordHasher):
        def verify(self, password, encoded):
            result = super().verify(password, encoded)
            service(storage).reset_password(token, NEW_PASSWORD, "fixture")
            return result

    store.hasher = RacingHasher()
    with pytest.raises(AuthDenied, match="password_credentials_invalid"):
        login(store)
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
    assert login(service(storage), password=NEW_PASSWORD)[1].user["email"] == EMAIL
