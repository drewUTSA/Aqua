"""Genuine sessions/roles with detached deterministic hashing and encrypted mail."""

import base64
from dataclasses import replace
import hashlib

import pytest

import main
from auth.mailconfig import MailPolicy
from auth.password_policy import PasswordPolicy
from auth.password_settings import get_password_store
from auth.passwords import PasswordStore
from auth.security import UserSession
from auth.sessions import session_cookie_name, token_digest

OLD = "Synthetic stable account password 27"
NEW = "Synthetic replacement account password 93"
PATH = "/api/v1/me"


class DetachedHasher:
    def __init__(self, storage) -> None:
        self.storage = storage
        self.calls = []
        self.on_verify = None
        self.on_hash = None

    @staticmethod
    def encoded(value: str) -> str:
        return "synthetic-account-hash-" + hashlib.sha256(value.encode()).hexdigest()

    def _free_lease(self) -> None:
        # With the fixture's one-slot pool this fails if hashing owns a lease.
        with self.storage.transaction() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)

    def hash(self, value: str) -> str:
        self._free_lease()
        self.calls.append("hash")
        if self.on_hash:
            self.on_hash()
        return self.encoded(value)

    def verify(self, value: str, encoded: str | None) -> bool:
        self._free_lease()
        self.calls.append("verify")
        if self.on_verify:
            self.on_verify()
        return encoded == self.encoded(value)

    def needs_rehash(self, encoded: str) -> bool:
        return False


class SecurityWorld:
    def __init__(self, world, monkeypatch) -> None:
        self.world = world
        self.hasher = DetachedHasher(world.storage)
        self.passwords = PasswordStore(
            world.storage,
            replace(world.policy, action_account_limit=30, action_global_limit=300),
            PasswordPolicy(),
            MailPolicy(True, b"s" * 32, world.settings.app_origin),
            hasher=self.hasher,
        )
        monkeypatch.setenv("PASSWORD_AUTH_ENABLED", "true")
        monkeypatch.setenv("ACCOUNT_MAIL_ENABLED", "true")
        monkeypatch.setenv("ACCOUNT_PUBLIC_ORIGIN", world.settings.app_origin)
        monkeypatch.setenv(
            "ACCOUNT_MAIL_OUTBOX_KEY", base64.urlsafe_b64encode(b"s" * 32).decode()
        )
        monkeypatch.setitem(
            main.app.dependency_overrides, get_password_store, lambda: self.passwords
        )

    def client(self, label="A", *, linked=True):
        client, owner = self.world.client(label, grant=False)
        if linked:
            with self.world.storage.transaction() as conn:
                conn.execute(
                    "INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version) VALUES(%s,%s,1) ON CONFLICT(user_id) DO NOTHING",
                    (owner, self.hasher.encoded(OLD)),
                )
        return client, owner

    def principal(self, client) -> UserSession:
        raw = client.cookies.get(session_cookie_name(self.world.settings))
        current = self.world.store.authenticate(token_digest(raw))
        return UserSession(
            current.user,
            client.headers["X-CSRF-Token"],
            token_digest(raw),
            current.can_query,
            current.grant_version,
            current.auth_epoch,
            current.dataset_key,
        )

    def target(self, operation, target=None) -> dict:
        return {
            "operation": operation,
            **({"target_session_id": target} if target is not None else {}),
        }

    def challenge(self, client, operation="password_change", target=None) -> dict:
        result = client.post(
            PATH + "/reauth-challenges", json=self.target(operation, target)
        )
        assert result.status_code == 200
        return result.json()

    def proof(self, client, operation="password_change", target=None) -> str:
        challenge = self.challenge(client, operation, target)
        result = client.post(
            PATH + "/reauth/password",
            json={
                **self.target(operation, target),
                "challenge_id": challenge["challenge_id"],
                "challenge_token": challenge["challenge_token"],
                "password": OLD,
            },
        )
        assert result.status_code == 200
        return result.json()["proof_token"]


@pytest.fixture
def account_security(world, monkeypatch):
    return SecurityWorld(world, monkeypatch)
