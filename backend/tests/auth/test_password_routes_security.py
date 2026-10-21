"""Attack the real password routes with synthetic storage and captured mail."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import threading
import unicodedata

from fastapi.testclient import TestClient
import pytest

import main
from auth.sessions import token_digest
from _auth_test_helpers import ORIGIN
from _password_route_helpers import COOKIE, EMAIL, PASSWORD, REPLACEMENT, ROOT, SESSION


@pytest.mark.parametrize("attack", ["origin", "missing", "wrong", "wrong-action"])
def test_invalid_bootstrap_csrf_never_hashes_or_sends_mail(password_browser, attack):
    browser = password_browser
    pending, _ = browser.bootstrap(
        "registration" if attack == "wrong-action" else "login"
    )
    headers = {"Origin": ORIGIN, "X-CSRF-Token": pending["csrf_token"]}
    if attack == "origin":
        headers["Origin"] = "https://attacker.invalid"
    elif attack == "missing":
        del headers["X-CSRF-Token"]
    elif attack == "wrong":
        headers["X-CSRF-Token"] = "invalid-csrf-canary"
    response = browser.client.post(
        ROOT + "/password-login",
        json={"email": EMAIL, "password": PASSWORD},
        headers=headers,
    )
    assert response.status_code == 403 and browser.hash_calls == []
    with browser.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "value", [PASSWORD * 100, {"secret": PASSWORD}], ids=["oversized", "nested"]
)
def test_invalid_password_body_is_not_reflected_or_hashed(
    password_browser, value, caplog
):
    browser = password_browser
    response = browser.post(
        "login", "/password-login", {"email": EMAIL, "password": value}
    )
    assert response.status_code == 422 and browser.hash_calls == []
    assert PASSWORD not in response.text + caplog.text
    assert "no-store" in response.headers["cache-control"]


def test_registration_activates_only_password_chosen_with_mailbox_proof(
    password_browser, caplog
):
    caplog.set_level("INFO", logger="aqua.password")
    browser = password_browser
    requested = browser.post("registration", "/registrations", {"email": EMAIL})
    assert requested.status_code == 202 and browser.hash_calls == []
    with browser.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)
    failed = browser.post(
        "verification",
        "/email-verifications",
        {"token": "A" * 43, "password": "Attacker chosen preregistration password 7!"},
    )
    assert failed.status_code == 400
    token = browser.mail_token("verify_email")
    response = browser.post(
        "verification", "/email-verifications", {"token": token, "password": PASSWORD}
    )
    assert response.status_code == 204 and browser.client.cookies.get(SESSION) is None
    assert (
        browser.login(
            password="Attacker chosen preregistration password 7!"
        ).status_code
        == 401
    )
    accepted = browser.login()
    assert accepted.status_code == 200 and accepted.json()["can_query"] is False
    assert set(accepted.json()["user"]) == {"id", "email", "name", "picture"}
    with browser.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.dataset_grants").fetchone() == (
            0,
        )
        rows = conn.execute("SELECT secret_digest FROM app.auth_challenges").fetchall()
        assert (hashlib.sha256(token.encode()).digest(),) in rows
        # Completing the email transition purges its bearer-bearing outbox job.
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
    for secret in (token, PASSWORD, browser.client.cookies.get(SESSION)):
        assert secret not in accepted.text + caplog.text
    assert (
        "password_event action=allow reason=registration_requested" in caplog.messages
    )
    assert "password_event action=allow reason=email_verified" in caplog.messages
    assert "password_event action=allow reason=session_created" in caplog.messages
    assert "password_event action=deny reason=credentials_invalid" in caplog.messages
    assert EMAIL not in caplog.text


def test_existing_registration_has_generic_ack_and_cannot_replace_credential(
    password_browser,
):
    browser = password_browser
    owner = browser.register()
    with browser.storage.transaction() as conn:
        before = conn.execute(
            "SELECT encoded_hash,auth_epoch FROM app.password_credentials p JOIN app.users u ON u.id=p.user_id WHERE p.user_id=%s",
            (owner,),
        ).fetchone()
    existing = browser.post("registration", "/registrations", {"email": EMAIL.upper()})
    unknown = browser.post(
        "registration", "/registrations", {"email": "new.reader@example.test"}
    )
    assert existing.status_code == unknown.status_code == 202
    assert existing.content == unknown.content
    with browser.storage.transaction() as conn:
        after = conn.execute(
            "SELECT encoded_hash,auth_epoch FROM app.password_credentials p JOIN app.users u ON u.id=p.user_id WHERE p.user_id=%s",
            (owner,),
        ).fetchone()
        assert after == before
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (1,)
    assert browser.login().status_code == 200


@pytest.mark.parametrize(
    "path,action",
    [("/email-verifications", "verification"), ("/password-resets", "reset")],
)
def test_recovery_links_do_not_mutate_on_get(password_browser, path, action):
    browser = password_browser
    browser.register()
    token = browser.reset_token() if action == "reset" else "A" * 43
    before = len(browser.hash_calls)
    response = browser.client.get(ROOT + path, params={"token": token})
    assert response.status_code in {404, 405} and len(browser.hash_calls) == before


@pytest.mark.parametrize("operation", ["verification", "reset"])
def test_concurrent_consumption_has_one_transition_and_no_automatic_login(
    password_browser, operation
):
    browser = password_browser
    if operation == "verification":
        assert (
            browser.post("registration", "/registrations", {"email": EMAIL}).status_code
            == 202
        )
        token = browser.mail_token("verify_email")
        path, password = "/email-verifications", PASSWORD
    else:
        browser.register()
        token = browser.reset_token()
        path, password = "/password-resets", REPLACEMENT
    # Distinct legitimate bootstrap challenges ensure this attacks the shared
    # email-token transition rather than the independent CSRF replay defense.
    attempts = [browser.bootstrap(operation) for _ in range(2)]
    gate = threading.Barrier(2)
    browser.storage.readiness()

    def submit(index):
        pending, cookie = attempts[index]
        copied = TestClient(main.app, base_url=ORIGIN)
        gate.wait(timeout=5)
        response = copied.post(
            ROOT + path,
            json={"token": token, "password": password},
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": pending["csrf_token"],
                "Cookie": f"{COOKIE}={cookie}",
            },
        )
        assert copied.cookies.get(SESSION) is None
        return response.status_code

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert sorted(workers.map(submit, range(2))) == [204, 400]
    with browser.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
    assert browser.login(password=password).status_code == 200


def test_reset_revokes_copied_sessions_and_all_outstanding_links(
    password_browser, caplog
):
    browser = password_browser
    owner = browser.register()
    first = browser.login()
    assert first.status_code == 200
    copied = browser.client.cookies.get(SESSION)
    second = browser.login()
    assert second.status_code == 200
    another = browser.client.cookies.get(SESSION)
    tokens = [browser.reset_token()]
    with browser.storage.transaction() as conn:
        # This scenario intentionally requests a second delivered link after
        # the recipient cooldown; the first live proof must still be revoked.
        conn.execute(
            "UPDATE app.mail_recipient_budget SET last_queued_at=clock_timestamp()-interval '6 minutes',"
            "issued_at=ARRAY(SELECT stamp-interval '6 minutes' FROM unnest(issued_at) stamp) "
            "WHERE purpose='reset_password'"
        )
    tokens.append(browser.reset_token())
    assert tokens[0] != tokens[1]
    changed = browser.post(
        "reset", "/password-resets", {"token": tokens[0], "password": REPLACEMENT}
    )
    assert changed.status_code == 204 and browser.client.cookies.get(SESSION) is None
    for cookie in (copied, another):
        response = TestClient(main.app, base_url=ORIGIN).get(
            "/api/auth/me", headers={"Cookie": f"{SESSION}={cookie}"}
        )
        assert response.status_code == 401
    assert (
        browser.post(
            "reset",
            "/password-resets",
            {
                "token": tokens[1],
                "password": "Second attempt to reuse password reset 9!",
            },
        ).status_code
        == 400
    )
    with browser.storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s AND revoked_at IS NULL",
            (owner,),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
    assert browser.login().status_code == 401
    assert browser.login(password=REPLACEMENT).status_code == 200
    assert all(
        value not in caplog.text
        for value in (*tokens, copied, another, PASSWORD, REPLACEMENT)
    )


def test_reset_does_not_create_first_password_for_google_only_identity(
    password_browser,
):
    from auth.store import IdentityStore
    from auth.sessions import new_token

    browser = password_browser
    identity = {
        "iss": "https://accounts.google.com",
        "sub": "fixture-google-only",
        "email": EMAIL,
        "email_verified": True,
        "name": "Synthetic Google reader",
    }
    existing = IdentityStore(browser.storage, browser.store.auth_policy).login(
        identity,
        token_digest(new_token()),
        token_digest(new_token()),
        "fixture",
        browser.settings,
    )
    existing_response = browser.post(
        "reset-request", "/password-reset-requests", {"email": EMAIL}
    )
    unknown_response = browser.post(
        "reset-request",
        "/password-reset-requests",
        {"email": "unknown.reset@example.test"},
    )
    assert existing_response.status_code == unknown_response.status_code == 202
    assert existing_response.content == unknown_response.content
    with browser.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials WHERE user_id=%s",
            (existing.user["id"],),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE purpose='password_reset'"
        ).fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
    assert browser.login().status_code == 401


def test_verification_token_cannot_be_used_for_recovery_or_activate_weak_password(
    password_browser,
):
    browser = password_browser
    assert (
        browser.post("registration", "/registrations", {"email": EMAIL}).status_code
        == 202
    )
    token = browser.mail_token("verify_email")
    swapped = browser.post(
        "reset", "/password-resets", {"token": token, "password": PASSWORD}
    )
    weak = browser.post(
        "verification",
        "/email-verifications",
        {"token": token, "password": "passwordpassword"},
    )
    assert swapped.status_code == 400 and weak.status_code == 422
    assert browser.hash_calls == []
    with browser.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at FROM app.auth_challenges WHERE secret_digest=%s",
            (hashlib.sha256(token.encode()).digest(),),
        ).fetchone() == (None,)
    assert (
        browser.post(
            "verification",
            "/email-verifications",
            {"token": token, "password": PASSWORD},
        ).status_code
        == 204
    )


def test_expired_mail_link_never_hashes_or_creates_an_account(password_browser):
    browser = password_browser
    assert (
        browser.post("registration", "/registrations", {"email": EMAIL}).status_code
        == 202
    )
    token = browser.mail_token("verify_email")
    with browser.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.auth_challenges SET created_at=now()-interval '2 days',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
            (hashlib.sha256(token.encode()).digest(),),
        )
    expired = browser.post(
        "verification", "/email-verifications", {"token": token, "password": PASSWORD}
    )
    assert expired.status_code == 400 and browser.hash_calls == []
    with browser.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (0,)


def test_password_at_normalized_limit_accepts_equivalent_decomposed_input(
    password_browser,
):
    browser = password_browser
    password = "é" * 124 + "xY9!"
    assert len(password) == 128
    decomposed = unicodedata.normalize("NFD", password)
    assert len(decomposed) > 128
    browser.register(password=password)
    assert browser.login(password=decomposed).status_code == 200
