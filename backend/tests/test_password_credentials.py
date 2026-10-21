"""Real isolated app-role account establishment and password/reset boundaries."""

import hashlib

import pytest

from auth.config import AuthDenied
from auth.mailconfig import MailPolicy, MailUnavailable
from auth.password_hash import PasswordHasher
from auth.store import IdentityStore
from password_core_helpers import (
    EMAIL,
    NEW_PASSWORD,
    PASSWORD,
    SETTINGS,
    digest,
    email_token,
    login,
    messages,
    register,
    service,
)


def test_request_stores_no_pending_account_password_or_plaintext_token(storage):
    store = service(storage)
    assert store.request_email(EMAIL, "verify_email", "fixture") is None
    token = email_token(storage, "verify_email")
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)
        owner, target, secret, epoch = conn.execute(
            "SELECT user_id,target_email_key,secret_digest,password_auth_epoch FROM app.auth_challenges"
        ).fetchone()
        assert (owner, target, epoch) == (None, EMAIL, None)
        assert bytes(secret) == hashlib.sha256(token.encode()).digest()
        assert (
            token.encode()
            not in conn.execute("SELECT ciphertext FROM app.account_mail").fetchone()[0]
        )
    owner = store.complete_verification(token, PASSWORD, "fresh-mailbox-browser")
    with storage.transaction() as conn:
        assert str(conn.execute("SELECT id FROM app.users").fetchone()[0]) == owner
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app.dataset_grants").fetchone() == (
            0,
        )
    secret, session = login(store)
    assert session.user["id"] == owner and not session.can_query
    assert IdentityStore(storage).authenticate(secret).user["id"] == owner


def test_repeated_registration_and_replayed_verification_never_replace_password(
    storage,
):
    store = service(storage)
    owner, token = register(store)
    assert store.request_email(EMAIL, "verify_email", "fixture") is None
    assert messages(storage, "verify_email") == []
    with pytest.raises(AuthDenied, match="email_challenge_invalid"):
        store.complete_verification(token, NEW_PASSWORD, "fixture")
    assert login(store)[1].user["id"] == owner
    with pytest.raises(AuthDenied):
        login(store, password=NEW_PASSWORD)


def test_pending_precreation_uses_recipients_fresh_password_and_consumes_all_links(
    storage,
):
    store = service(storage)
    store.request_email(EMAIL, "verify_email", "untrusted-requester")
    older = email_token(storage, "verify_email")
    store.request_email(EMAIL, "verify_email", "mailbox-browser")
    newer = email_token(storage, "verify_email")
    owner = store.complete_verification(newer, NEW_PASSWORD, "mailbox-browser")
    with pytest.raises(AuthDenied):
        store.complete_verification(older, PASSWORD, "untrusted-requester")
    assert login(store, password=NEW_PASSWORD)[1].user["id"] == owner
    with pytest.raises(AuthDenied):
        login(store, password=PASSWORD)


def test_google_only_collision_and_reset_never_link_or_create_first_password(storage):
    store = service(storage)
    store.request_email(EMAIL, "verify_email", "fixture")
    token = email_token(storage, "verify_email")
    google = IdentityStore(storage).login(
        {"sub": "google-only", "email": EMAIL, "email_verified": True},
        digest(),
        digest(),
        "fixture",
        SETTINGS,
    )
    with pytest.raises(AuthDenied):
        store.complete_verification(token, PASSWORD, "fixture")
    assert store.request_email(EMAIL, "password_reset", "fixture") is None
    assert (
        store.request_email("unknown@example.invalid", "password_reset", "fixture")
        is None
    )
    assert messages(storage, "reset_password") == []
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)
        assert (
            str(conn.execute("SELECT id FROM app.users").fetchone()[0])
            == google.user["id"]
        )
    with pytest.raises(AuthDenied):
        login(store)


def test_reset_revokes_copied_sessions_all_links_and_notifies_without_auto_login(
    storage,
):
    store = service(storage)
    owner, _ = register(store)
    first, _ = login(store)
    second, _ = login(store)
    store.request_email(EMAIL, "password_reset", "fixture")
    older = email_token(storage, "reset_password")
    store.request_email(EMAIL, "password_reset", "fixture")
    token = email_token(storage, "reset_password")
    assert store.reset_password(token, NEW_PASSWORD, "fixture") is None
    for copied in (first, second):
        with pytest.raises(AuthDenied):
            IdentityStore(storage).authenticate(copied)
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE revoked_at IS NULL"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE purpose='password_reset' AND consumed_at IS NULL"
        ).fetchone() == (0,)
    assert len(messages(storage, "password_changed")) == 1
    for replay in (older, token):
        with pytest.raises(AuthDenied):
            store.reset_password(replay, PASSWORD, "fixture")
    with pytest.raises(AuthDenied):
        login(store)
    assert login(store, password=NEW_PASSWORD)[1].user["id"] == owner


@pytest.mark.parametrize("purpose", ["verify_email", "password_reset"])
def test_expired_or_wrong_purpose_email_tokens_cannot_change_credentials(
    storage, purpose
):
    store = service(storage)
    if purpose == "password_reset":
        register(store)
    store.request_email(EMAIL, purpose, "fixture")
    token = email_token(
        storage, "verify_email" if purpose == "verify_email" else "reset_password"
    )
    wrong = (
        store.reset_password
        if purpose == "verify_email"
        else store.complete_verification
    )
    with pytest.raises(AuthDenied):
        wrong(token, NEW_PASSWORD, "fixture")
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.auth_challenges SET created_at=now()-interval '2 days',expires_at=now()-interval '1 second' WHERE purpose=%s",
            (purpose,),
        )
    correct = (
        store.complete_verification
        if purpose == "verify_email"
        else store.reset_password
    )
    with pytest.raises(AuthDenied):
        correct(token, NEW_PASSWORD, "fixture")


def test_mail_outage_is_uniform_for_known_unknown_and_does_not_break_login(storage):
    store = service(storage)
    register(store)
    store.mail_policy = MailPolicy()
    for address in (EMAIL, "unknown@example.invalid"):
        with pytest.raises(MailUnavailable):
            store.request_email(address, "password_reset", "fixture")
    assert login(store)[1].user["email"] == EMAIL


def test_argon2_never_holds_the_only_app_connection_and_unknown_does_equivalent_work(
    storage,
):
    store = service(storage)
    seen = []

    class CheckingHasher(PasswordHasher):
        def hash(self, password):
            with storage.transaction() as conn:
                assert conn.execute("SELECT 1").fetchone() == (1,)
            seen.append("hash")
            return super().hash(password)

        def verify(self, password, encoded):
            with storage.transaction() as conn:
                assert conn.execute("SELECT 1").fetchone() == (1,)
            seen.append("verify")
            return super().verify(password, encoded)

    store.hasher = CheckingHasher()
    register(store)
    login(store)
    with pytest.raises(AuthDenied):
        login(store, email="unknown@example.invalid")
    with pytest.raises(AuthDenied):
        login(store, password=NEW_PASSWORD)
    assert seen == ["hash", "verify", "verify", "verify"]
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
