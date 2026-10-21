"""Synthetic browser/mail fixtures for password boundary regression tests."""

from dataclasses import dataclass, replace
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest

import main
from auth.config import load_auth_policy
from auth.mailconfig import MailPolicy
from auth.mailoutbox import open_job
from auth.password_policy import PasswordPolicy
from storage.pool import Storage
from _auth_test_helpers import ORIGIN

ROOT = "/api/v1/auth"
COOKIE = "__Host-aqua_password"
SESSION = "__Host-aqua_session"
EMAIL = "local.reader@example.test"
PASSWORD = "Synthetic secret for reader 429!"
REPLACEMENT = "Different synthetic secret after recovery 731!"


@dataclass
class PasswordBrowser:
    client: TestClient
    storage: Storage
    store: object
    mail_policy: MailPolicy
    hash_calls: list[str]
    settings: object

    def bootstrap(self, action: str) -> tuple[dict, str]:
        response = self.client.get(ROOT + "/bootstrap", params={"action": action})
        assert response.status_code == 200
        assert "no-store" in response.headers["cache-control"]
        attributes = response.headers["set-cookie"].lower()
        assert all(
            flag in attributes
            for flag in ("httponly", "secure", "samesite=lax", "path=/")
        )
        assert "domain=" not in attributes
        cookie = self.client.cookies.get(COOKIE)
        assert cookie and cookie not in response.text
        return response.json(), cookie

    def post(self, action: str, path: str, payload: dict):
        pending, _ = self.bootstrap(action)
        return self.client.post(
            ROOT + path,
            json=payload,
            headers={"Origin": ORIGIN, "X-CSRF-Token": pending["csrf_token"]},
        )

    def mail_token(self, purpose: str) -> str:
        """Decrypt a synthetic queued message locally; never invoke a provider."""
        from auth.mailqueue import MailOutbox

        queue = MailOutbox(self.storage, self.mail_policy)
        for _ in range(8):
            job = queue.claim()
            assert job is not None, "expected a synthetic account message"
            payload = open_job(job, self.mail_policy)
            assert payload["to"].encode() not in job.ciphertext
            assert payload["text"].encode() not in job.ciphertext
            assert queue.finish(job, "accepted")
            # Advance only the isolated fixture's delivery spacing clock.
            with self.storage.transaction() as conn:
                conn.execute(
                    "UPDATE app.account_mail_control SET last_attempt_at=clock_timestamp()-interval '2 seconds' WHERE singleton"
                )
            if job.purpose == purpose:
                line = next(
                    line
                    for line in payload["text"].splitlines()
                    if line.startswith("https://")
                )
                parsed = urlsplit(line)
                assert parsed.scheme + "://" + parsed.netloc == ORIGIN
                assert not parsed.query
                return parse_qs(parsed.fragment)["token"][0]
        raise AssertionError("bounded fixture mailbox did not contain expected purpose")

    def register(self, email: str = EMAIL, password: str = PASSWORD) -> str:
        response = self.post("registration", "/registrations", {"email": email})
        assert response.status_code == 202
        token = self.mail_token("verify_email")
        verified = self.post(
            "verification",
            "/email-verifications",
            {"token": token, "password": password},
        )
        assert verified.status_code == 204
        assert self.client.cookies.get(SESSION) is None
        with self.storage.transaction() as conn:
            return str(
                conn.execute(
                    "SELECT user_id FROM app.user_emails WHERE email_key=%s",
                    (email.lower(),),
                ).fetchone()[0]
            )

    def login(self, email: str = EMAIL, password: str = PASSWORD):
        return self.post(
            "login", "/password-login", {"email": email, "password": password}
        )

    def reset_token(self, email: str = EMAIL) -> str:
        response = self.post(
            "reset-request", "/password-reset-requests", {"email": email}
        )
        assert response.status_code == 202
        return self.mail_token("reset_password")


@pytest.fixture
def password_browser(storage, monkeypatch):
    """One bounded DB lease proves hash execution never retains a transaction."""
    from auth import password_router
    from auth.password_hash import PasswordHasher
    from auth.passwords import PasswordStore

    service = Storage(replace(storage.settings, max_waiting=4, wait_seconds=2))
    settings = replace(
        main.app.state.settings,
        google_client_id="",
        app_origin=ORIGIN,
        session_secret="password-route-fixture-secret-" * 3,
        auth_allowed_emails=frozenset(),
        auth_allowed_google_subs=frozenset(),
    )
    monkeypatch.setattr(main.app.state, "settings", settings)
    monkeypatch.setattr(main.app.state, "storage", service)
    monkeypatch.setenv("PASSWORD_AUTH_ENABLED", "true")
    monkeypatch.setenv("PASSWORD_REGISTRATION_ENABLED", "true")
    monkeypatch.setenv("PASSWORD_RECOVERY_ENABLED", "true")
    policy = replace(
        PasswordPolicy(),
        login_peer_limit=300,
        login_global_limit=300,
        login_address_limit=300,
        mail_peer_limit=300,
        mail_global_limit=300,
        mail_address_limit=300,
        consume_peer_limit=300,
        consume_global_limit=300,
    )
    auth_policy = replace(
        load_auth_policy(settings),
        challenge_peer_limit=300,
        challenge_global_limit=300,
        login_peer_limit=300,
        login_global_limit=300,
        login_account_limit=300,
    )
    mail_policy = MailPolicy(enabled=True, key=bytes(range(32)), public_origin=ORIGIN)
    calls = []
    hasher = PasswordHasher()
    original_hash, original_verify = hasher.hash, hasher.verify

    def record(operation, function):
        def invoke(*args, **kwargs):
            with service.transaction() as conn:
                assert conn.execute("SELECT 1").fetchone() == (1,)
            calls.append(operation)
            return function(*args, **kwargs)

        return invoke

    monkeypatch.setattr(hasher, "hash", record("hash", original_hash))
    monkeypatch.setattr(hasher, "verify", record("verify", original_verify))
    store = PasswordStore(service, auth_policy, policy, mail_policy, hasher=hasher)
    previous = dict(main.app.dependency_overrides)
    main.app.dependency_overrides[password_router.get_password_store] = lambda: store
    try:
        with TestClient(main.app, base_url=ORIGIN) as client:
            yield PasswordBrowser(client, service, store, mail_policy, calls, settings)
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(previous)
        service.close()
