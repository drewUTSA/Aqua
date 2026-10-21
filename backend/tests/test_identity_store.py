"""Real isolated app-role tests: canonical ownership, revocation and session caps."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import hashlib
import uuid

import pytest

from auth.config import AuthDenied, AuthLimited, AuthPolicy, dataset_key
from auth.store import ACTIVE_SESSIONS_SQL, IdentityStore
from nl2sql.config import Settings
from storage.pool import Storage, StorageUnavailable

EMAIL = "identity.fixture@gmail.com"
SETTINGS = Settings(database_url="synthetic-bank-dataset")
IDENTITY = {
    "sub": "google-fixture-A",
    "email": EMAIL,
    "email_verified": True,
    "name": "Synthetic A",
    "picture": "https://lh3.googleusercontent.com/fixture",
}


def token() -> bytes:
    return hashlib.sha256(uuid.uuid4().bytes).digest()


def service(storage, **changes) -> IdentityStore:
    policy = AuthPolicy(dataset_key=dataset_key(SETTINGS), login_account_limit=100)
    return IdentityStore(storage, replace(policy, **changes))


def login(store, identity=None):
    secret, csrf = token(), token()
    session = store.login(identity or IDENTITY, secret, csrf, "fixture-peer", SETTINGS)
    return secret, csrf, session


def test_canonical_identity_survives_new_session_without_automatic_grant(storage):
    store = service(storage)
    first, csrf, a = login(store)
    _, _, b = login(store)
    assert a.user["id"] == b.user["id"] != IDENTITY["sub"]
    assert a.id != b.id and a.csrf_digest == csrf
    assert a.user["email"] == EMAIL and a.can_query is False
    assert store.authenticate(first).user == a.user
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM app.dataset_grants").fetchone() == (
            0,
        )
        assert conn.execute(
            "SELECT octet_length(token_digest),octet_length(csrf_digest) FROM app.sessions LIMIT 1"
        ).fetchone() == (32, 32)
        assert conn.execute(
            "SELECT user_id,schema_version,revision,values FROM app.user_preferences"
        ).fetchall() == [(uuid.UUID(a.user["id"]), 1, 1, {})]


def test_email_collision_never_merges_subjects_or_leaves_an_orphan(storage):
    store = service(storage)
    _, _, a = login(store)
    with pytest.raises(AuthDenied, match="identity_conflict"):
        login(store, {**IDENTITY, "sub": "different-subject"})
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (1,)
        assert conn.execute("SELECT user_id FROM app.external_identities").fetchone()[
            0
        ] == uuid.UUID(a.user["id"])


def test_subject_is_case_sensitive_and_email_change_keeps_canonical_account(storage):
    store = service(storage)
    _, _, first = login(store)
    _, _, changed = login(store, {**IDENTITY, "email": "changed.fixture@gmail.com"})
    _, _, different = login(
        store,
        {**IDENTITY, "sub": IDENTITY["sub"].lower(), "email": "case.fixture@gmail.com"},
    )
    assert first.user["id"] == changed.user["id"] != different.user["id"]
    assert changed.user["email"] == "changed.fixture@gmail.com"


@pytest.mark.parametrize(
    "change",
    [
        {"email_verified": False},
        {"sub": ""},
        {"iss": "https://evil.invalid"},
        {"email": "bad @gmail.com"},
    ],
)
def test_store_rejects_incomplete_or_wrong_issuer_claims(storage, change):
    with pytest.raises(AuthDenied):
        login(service(storage), {**IDENTITY, **change})
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (0,)


def test_first_login_and_email_collision_races_are_transactional(storage):
    other = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )
    try:
        stores = [service(storage), service(other)]
        with ThreadPoolExecutor(max_workers=2) as threads:
            results = list(threads.map(lambda i: login(stores[i])[2], range(2)))
        assert results[0].user["id"] == results[1].user["id"]
        with storage.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (1,)
    finally:
        other.close()


def test_parallel_different_subjects_cannot_claim_one_email(storage):
    other = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )

    def attempt(index):
        try:
            login(
                service(storage if index == 0 else other),
                {**IDENTITY, "sub": f"racing-sub-{index}"},
            )
            return "accepted"
        except AuthDenied:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as threads:
            assert sorted(threads.map(attempt, range(2))) == ["accepted", "denied"]
        with storage.transaction() as conn:
            assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (1,)
    finally:
        other.close()


def test_session_cap_is_atomic_across_store_instances_and_recovers_on_logout(storage):
    other = Storage(
        replace(storage.settings, max_connections=2, max_waiting=4, wait_seconds=2)
    )
    stores = [service(storage, max_sessions=1), service(other, max_sessions=1)]

    def attempt(index):
        try:
            return login(stores[index])[0]
        except AuthLimited:
            return None

    try:
        with ThreadPoolExecutor(max_workers=2) as threads:
            results = list(threads.map(attempt, range(2)))
        accepted = [item for item in results if item is not None]
        assert len(accepted) == 1
        stores[0].revoke(accepted[0])
        with pytest.raises(AuthDenied):
            stores[1].authenticate(accepted[0])
        assert login(stores[1])[2].user["id"]
    finally:
        other.close()


def test_idle_expired_history_does_not_scan_or_exhaust_live_session_capacity(
    storage, app_database
):
    """Measured live-row seek against 5,000 retained but idle-expired sessions."""
    store = service(storage, max_sessions=2)
    _, _, first = login(store)
    with storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,"
            "created_at,idle_expires_at,absolute_expires_at) "
            "SELECT %s,decode(md5('bulk-'||n::text)||md5('tail-'||n::text),'hex'),"
            "%s,0,'google',now()-interval '2 hours',now()-interval '1 hour',"
            "now()+interval '1 hour' FROM generate_series(1,5000) n",
            (first.user["id"], token()),
        )
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute("ANALYZE app.sessions")
    app_database.execute("RESET ROLE")
    assert login(store)[2].user["id"] == first.user["id"]
    with pytest.raises(AuthLimited):
        login(store)
    with storage.transaction() as conn:
        instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        explained = conn.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + ACTIVE_SESSIONS_SQL,
            (first.user["id"], 0, instant, store.policy.max_sessions),
        ).fetchone()[0][0]["Plan"]

    def nodes(plan):
        yield plan
        for child in plan.get("Plans", []):
            yield from nodes(child)

    assert explained["Actual Rows"] == 2
    assert any(
        node.get("Index Name") == "sessions_owner_epoch_idle"
        for node in nodes(explained)
    )
    assert (
        explained.get("Shared Hit Blocks", 0) + explained.get("Shared Read Blocks", 0)
        <= 64
    )


@pytest.mark.parametrize(
    "mutation", ["status='disabled'", "status='deleting'", "auth_epoch=auth_epoch+1"]
)
def test_current_account_state_revokes_copied_session(storage, mutation):
    store = service(storage)
    secret, _, session = login(store)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.users SET " + mutation + " WHERE id=%s", (session.user["id"],)
        )
    with pytest.raises(AuthDenied):
        store.authenticate(secret)


@pytest.mark.parametrize("expiry", ["idle", "absolute"])
def test_both_server_expiry_boundaries_reject_old_cookie(storage, expiry):
    store = service(storage)
    secret, _, session = login(store)
    with storage.transaction() as conn:
        if expiry == "idle":
            conn.execute(
                "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '1 second' WHERE id=%s",
                (session.id,),
            )
        else:
            conn.execute(
                "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '2 seconds',absolute_expires_at=now()-interval '1 second' WHERE id=%s",
                (session.id,),
            )
    with pytest.raises(AuthDenied):
        store.authenticate(secret)


def test_polling_does_not_refresh_idle_but_meaningful_activity_is_bounded(storage):
    store = service(storage)
    secret, _, session = login(store)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET idle_expires_at=now()+interval '60 seconds' WHERE id=%s",
            (session.id,),
        )
        before = conn.execute(
            "SELECT idle_expires_at,authenticated_at FROM app.sessions WHERE id=%s",
            (session.id,),
        ).fetchone()
    store.authenticate(secret)
    with storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT idle_expires_at,authenticated_at FROM app.sessions WHERE id=%s",
                (session.id,),
            ).fetchone()
            == before
        )
    store.authenticate(secret, meaningful_activity=True)
    with storage.transaction() as conn:
        idle, absolute, authenticated = conn.execute(
            "SELECT idle_expires_at,absolute_expires_at,authenticated_at FROM app.sessions WHERE id=%s",
            (session.id,),
        ).fetchone()
        assert before[0] < idle <= absolute and authenticated == before[1]


def test_grant_revocation_is_immediate_and_login_never_resurrects_it(storage):
    store = service(storage, allowed_emails=frozenset({EMAIL}))
    secret, _, a = login(store)
    assert a.can_query and a.grant_version == 1
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.dataset_grants SET revoked_at=now() WHERE user_id=%s",
            (a.user["id"],),
        )
    revoked = store.authenticate(secret)
    assert not revoked.can_query and revoked.grant_version == 2
    assert not login(store)[2].can_query
    assert not service(storage).authenticate(secret).can_query


@pytest.mark.parametrize(
    "email,hd,subjects,allowed",
    [
        ("reader@company.invalid", "", frozenset(), False),
        ("reader@company.invalid", "company.invalid", frozenset(), True),
        ("reader@company.invalid", "", frozenset({IDENTITY["sub"]}), True),
    ],
)
def test_legacy_grants_require_fresh_authoritative_email_or_explicit_subject(
    storage, email, hd, subjects, allowed
):
    store = service(
        storage, allowed_emails=frozenset({email}), allowed_google_subs=subjects
    )
    secret, _, session = login(store, {**IDENTITY, "email": email, "hd": hd})
    assert session.can_query is allowed
    assert not service(storage).authenticate(secret).can_query
    changed = service(
        storage,
        dataset_key="a" * 64,
        allowed_emails=frozenset({email}),
        allowed_google_subs=subjects,
    )
    assert not changed.authenticate(secret).can_query


def test_grant_provenance_cannot_reference_another_users_identity(storage):
    store = service(storage)
    _, _, a = login(store)
    _, _, b = login(
        store, {**IDENTITY, "sub": "google-B", "email": "b.fixture@gmail.com"}
    )
    with storage.transaction() as conn:
        identity_id = conn.execute(
            "SELECT id FROM app.external_identities WHERE user_id=%s", (b.user["id"],)
        ).fetchone()[0]
    with pytest.raises(StorageUnavailable):
        with storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) VALUES (%s,%s,'google_subject',%s,'google-B')",
                (a.user["id"], store.policy.dataset_key, identity_id),
            )


@pytest.mark.parametrize(
    "hosted_domain",
    [True, 1, {"domain": "company.invalid"}, ["company.invalid"], " ", "x" * 254],
)
def test_malformed_hosted_domain_never_confers_email_authority(storage, hosted_domain):
    email = "reader@company.invalid"
    store = service(storage, allowed_emails=frozenset({email}))
    _, _, session = login(store, {**IDENTITY, "email": email, "hd": hosted_domain})
    assert not session.can_query
