"""Exercise the login and mailbox boundary with one synthetic operator invitation."""

import base64
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread

import pytest

from _password_route_helpers import PASSWORD, SESSION

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "ops/accounts/invite.py"
ADDRESS = "owner+sample-employee@example.test"
ACCEPTED = b"Invitation request accepted.\n"
UNAVAILABLE = b"Invitation unavailable.\n"


@pytest.fixture
def operator(password_browser, monkeypatch):
    browser = password_browser
    for key, value in {
        "APP_DATABASE_URL": browser.storage.settings.dsn,
        "APP_STORAGE_ENABLED": "true",
        "APP_DB_POOL_SIZE": "2",
        "APP_ORIGIN": browser.settings.app_origin,
        "SESSION_SECRET": browser.settings.session_secret,
        "ACCOUNT_PUBLIC_ORIGIN": browser.mail_policy.public_origin,
        "ACCOUNT_MAIL_ENABLED": "true",
        "ACCOUNT_MAIL_OUTBOX_KEY": base64.urlsafe_b64encode(
            browser.mail_policy.key
        ).decode(),
        "PASSWORD_REGISTRATION_ENABLED": "false",
    }.items():
        monkeypatch.setenv(key, value)

    class Readiness(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/api/ready"
            response = browser.client.get(self.path)
            self.send_response(response.status_code)
            self.end_headers()
            self.wfile.write(response.content)

        def log_message(self, *args):
            pass

    # The operator connects only to port 8000 inside the actual backend container.
    with HTTPServer(("127.0.0.1", 8000), Readiness) as web:
        thread = Thread(target=web.serve_forever, daemon=True)
        thread.start()
        try:
            yield browser
        finally:
            web.shutdown()
            thread.join(2)


def invoke(data, *args, **environment):
    return subprocess.run(
        [sys.executable, "-B", str(SCRIPT), *args],
        env={**os.environ, **environment, "PYTHONPATH": str(ROOT / "backend")},
        input=data,
        capture_output=True,
        timeout=10,
        check=False,
    )


def assert_private_failure(result):
    assert (result.returncode, result.stdout, result.stderr) == (1, b"", UNAVAILABLE)


def records(browser):
    with browser.storage.transaction() as conn:
        return conn.execute(
            "SELECT (SELECT count(*) FROM app.users),(SELECT count(*) FROM app.sessions),"
            "(SELECT count(*) FROM app.dataset_grants),"
            "(SELECT count(*) FROM app.auth_challenges WHERE purpose='verify_email'),"
            "(SELECT count(*) FROM app.account_mail WHERE purpose='verify_email')"
        ).fetchone()


def test_restricted_invite_requires_mailbox_and_login_grants_nothing(operator):
    browser = operator
    registration = browser.client.get(
        "/api/v1/auth/bootstrap", params={"action": "registration"}
    )
    assert registration.status_code == 503
    data = ADDRESS.upper().encode() + b"\r\n"
    for _ in range(2):
        result = invoke(data)
        assert (result.returncode, result.stdout, result.stderr) == (0, ACCEPTED, b"")
        assert records(browser) == (0, 0, 0, 1, 1)
    token = browser.mail_token("verify_email")
    proof = {"token": token, "password": PASSWORD}
    assert (
        browser.post("verification", "/email-verifications", proof).status_code == 204
    )
    assert browser.client.cookies.get(SESSION) is None
    assert (
        browser.post("verification", "/email-verifications", proof).status_code == 400
    )
    logged_in = browser.login(ADDRESS)
    assert logged_in.status_code == 200 and logged_in.json()["can_query"] is False
    assert records(browser) == (1, 1, 0, 1, 0)
    assert browser.client.get("/api/auth/me").json()["user"]["email"] == ADDRESS
    known = invoke(data)
    assert (known.returncode, known.stdout, known.stderr) == (0, ACCEPTED, b"")
    assert records(browser) == (1, 1, 0, 1, 0)
    assert (
        browser.client.get(
            "/api/v1/auth/bootstrap", params={"action": "registration"}
        ).status_code
        == 503
    )


@pytest.mark.parametrize(
    "change",
    [
        {"ACCOUNT_MAIL_ENABLED": "false"},
        {"PASSWORD_AUTH_ENABLED": "false"},
        {"ACCOUNT_PUBLIC_ORIGIN": "https://other.example.test"},
        {"PASSWORD_VERIFICATION_SECONDS": "30"},
    ],
)
def test_disabled_or_inconsistent_settings_refuse_without_writes(operator, change):
    assert_private_failure(invoke(ADDRESS.encode(), **change))
    assert records(operator) == (0, 0, 0, 0, 0)


def test_recovery_and_unmounted_authority_refuse_before_issuance(operator):
    with operator.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.retirement_control SET recovery_required=true WHERE singleton"
        )
    assert_private_failure(invoke(ADDRESS.encode()))
    with operator.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.retirement_control SET recovery_required=false,authority_installed=true WHERE singleton"
        )
    assert_private_failure(invoke(ADDRESS.encode()))
    assert records(operator) == (0, 0, 0, 0, 0)


def test_mailbox_claimed_before_verification_cannot_link_or_replace_google(operator):
    from auth.sessions import new_token, token_digest
    from auth.store import IdentityStore

    original = invoke(ADDRESS.encode())
    assert original.returncode == 0 and original.stdout == ACCEPTED
    token = operator.mail_token("verify_email")
    IdentityStore(operator.storage, operator.store.auth_policy).login(
        {
            "iss": "https://accounts.google.com",
            "sub": "synthetic-operator-invite",
            "email": ADDRESS,
            "email_verified": True,
            "name": "Fixture employee",
        },
        token_digest(new_token()),
        token_digest(new_token()),
        "fixture",
        operator.settings,
    )
    assert (
        operator.post(
            "verification",
            "/email-verifications",
            {"token": token, "password": PASSWORD},
        ).status_code
        == 400
    )
    duplicate = invoke(ADDRESS.encode())
    assert (duplicate.returncode, duplicate.stdout, duplicate.stderr) == (
        0,
        ACCEPTED,
        b"",
    )
    assert records(operator) == (1, 1, 0, 1, 1)
    with operator.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials"
        ).fetchone() == (0,)


def test_private_input_and_cli_output_are_bounded():
    for value in (
        b"",
        b" " + ADDRESS.encode(),
        b"x" * 258,
        b"\xff",
        (ADDRESS + "\n" + ADDRESS).encode(),
    ):
        assert_private_failure(invoke(value))
    assert_private_failure(invoke(b"", ADDRESS))
