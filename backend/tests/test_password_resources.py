"""Expiration, session capacity and token ownership remain bounded and recoverable."""

from dataclasses import replace

import pytest

from auth.config import AuthDenied, AuthLimited
from auth.store import IdentityStore
from password_core_helpers import (
    EMAIL,
    NEW_PASSWORD,
    PASSWORD,
    email_token,
    login,
    register,
    service,
)


def test_pending_mail_never_reserves_email_and_expiry_allows_fresh_registration(
    storage,
):
    store = service(storage)
    for _ in range(4):
        store.request_email(EMAIL, "verify_email", "fixture")
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE purpose='verify_email'"
        ).fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM app.user_emails").fetchone() == (0,)
        conn.execute(
            "UPDATE app.auth_challenges SET created_at=now()-interval '2 days',expires_at=now()-interval '1 second' WHERE purpose='verify_email'"
        )
    with storage.transaction() as conn:
        # This test intentionally simulates expired delivery and a later resend.
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=clock_timestamp()-interval '6 minutes',issued_at=ARRAY[clock_timestamp()-interval '6 minutes']"
        )
    store.request_email(EMAIL, "verify_email", "fixture")
    token = email_token(storage, "verify_email")
    assert store.complete_verification(token, PASSWORD, "fixture")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)


def test_global_challenge_cap_denies_without_eviction_then_bounded_cleanup_recovers(
    storage,
):
    store = service(storage, max_challenges=8)
    for index in range(8):
        store.request_email(
            f"bounded{index}@example.invalid", "verify_email", "fixture"
        )
    with pytest.raises(AuthLimited):
        store.request_email("bounded9@example.invalid", "verify_email", "fixture")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.auth_challenges").fetchone() == (
            8,
        )
        conn.execute(
            "UPDATE app.auth_challenges SET created_at=now()-interval '2 days',expires_at=now()-interval '1 second'"
        )
    store.request_email("bounded9@example.invalid", "verify_email", "fixture")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.auth_challenges").fetchone() == (
            1,
        )
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (1,)


def test_password_sessions_share_google_cap_and_recover_after_revocation(storage):
    store = service(storage)
    store.auth_policy = replace(store.auth_policy, max_sessions=1)
    owner, _ = register(store)
    token, first = login(store)
    with pytest.raises(AuthLimited):
        login(store)
    IdentityStore(storage).revoke(token)
    new_token, second = login(store)
    assert first.id != second.id and second.user["id"] == owner
    assert new_token != token


def test_reset_cannot_retarget_token_to_another_accounts_email_or_epoch(storage):
    store = service(storage)
    owner, _ = register(store)
    other, _ = register(store, "other@example.invalid")
    store.request_email(EMAIL, "password_reset", "fixture")
    token = email_token(storage, "reset_password")
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.auth_challenges SET target_email_key='other@example.invalid' WHERE purpose='password_reset'"
        )
    with pytest.raises(AuthDenied):
        store.reset_password(token, NEW_PASSWORD, "fixture")
    assert login(store)[1].user["id"] == owner
    assert login(store, email="other@example.invalid")[1].user["id"] == other


@pytest.mark.parametrize("status", ["disabled", "deleting", "pending"])
def test_disabled_or_unverified_users_do_not_gain_password_sessions(storage, status):
    store = service(storage)
    owner, _ = register(store)
    with storage.transaction() as conn:
        conn.execute("UPDATE app.users SET status=%s WHERE id=%s", (status, owner))
    with pytest.raises(AuthDenied):
        login(store)
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
