"""Synthetic provider assertions and encrypted mailbox capture, never real I/O."""

from dataclasses import replace
import re
import time
from uuid import uuid4

import pytest
import main
from account.identity_runtime import get_identity_passwords
from auth.mailoutbox import MailJob, open_job
from security_action_fixtures import OLD, PATH, SecurityWorld


class IdentityWorld(SecurityWorld):
    def __init__(self, world, monkeypatch):
        super().__init__(world, monkeypatch)
        world.settings = replace(
            world.settings,
            google_client_id="synthetic-account-client.apps.googleusercontent.com",
        )
        monkeypatch.setattr(main.app.state, "settings", world.settings)
        monkeypatch.setitem(
            main.app.dependency_overrides,
            get_identity_passwords,
            lambda: self.passwords,
        )
        self.assertions, self.provider_calls, self.on_google = {}, [], None
        import account.google_verification as module

        monkeypatch.setattr(module, "verify_google_token", self.verify_google)

    def verify_google(self, credential, client_id):
        self.hasher._free_lease()
        self.provider_calls.append((credential, client_id))
        if self.on_google:
            self.on_google()
        return dict(self.assertions[credential])

    def assertion(
        self, expected_nonce, *, subject="workspace-A", email="a@gmail.com", **changes
    ):
        credential = "synthetic-private-credential-" + uuid4().hex
        self.assertions[credential] = {
            "iss": "https://accounts.google.com",
            "aud": self.world.settings.google_client_id,
            "sub": subject,
            "email": email,
            "email_verified": True,
            "nonce": expected_nonce,
            "iat": int(time.time()),
            "exp": int(time.time()) + 300,
            **changes,
        }
        return credential

    @staticmethod
    def identity_target(operation, target=None):
        key = {
            "email_change": "new_email",
            "google_unlink": "target_identity_id",
            "session_revoke": "target_session_id",
        }.get(operation)
        return {"operation": operation, **({key: target} if key else {})}

    def google_start(self, client, operation="password_add", target=None):
        principal = self.principal(client)
        with self.world.storage.transaction() as conn:
            identity = str(
                conn.execute(
                    "SELECT id FROM app.external_identities WHERE user_id=%s AND is_active ORDER BY id LIMIT 1",
                    (principal.user["id"],),
                ).fetchone()[0]
            )
        response = client.post(
            PATH + "/reauth/google-challenges",
            json={**self.identity_target(operation, target), "identity_id": identity},
        )
        assert response.status_code == 200, response.text
        return response.json()

    def google_proof(self, client, operation="password_add", target=None, **claims):
        start = self.google_start(client, operation, target)
        principal = self.principal(client)
        with self.world.storage.transaction() as conn:
            subject, email = conn.execute(
                "SELECT subject,observed_email_key FROM app.external_identities WHERE user_id=%s AND is_active ORDER BY id LIMIT 1",
                (principal.user["id"],),
            ).fetchone()
        credential = self.assertion(
            start["nonce"], subject=subject, email=email, **claims
        )
        response = client.post(
            PATH + "/reauth/google",
            json={
                **self.identity_target(operation, target),
                "challenge_id": start["challenge_id"],
                "challenge_token": start["challenge_token"],
                "credential": credential,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["proof_token"]

    def password_proof(self, client, operation, target=None):
        body = self.identity_target(operation, target)
        start = client.post(PATH + "/reauth-challenges", json=body)
        assert start.status_code == 200, start.text
        response = client.post(
            PATH + "/reauth/password",
            json={
                **body,
                "challenge_id": start.json()["challenge_id"],
                "challenge_token": start.json()["challenge_token"],
                "password": OLD,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["proof_token"]

    def candidate(
        self,
        client,
        proof,
        *,
        subject="new-synthetic-google",
        email="new-google@example.invalid",
    ):
        start = client.post(
            PATH + "/google-link-challenges", json={"proof_token": proof}
        )
        assert start.status_code == 200, start.text
        credential = self.assertion(start.json()["nonce"], subject=subject, email=email)
        response = client.post(
            PATH + "/google-link-candidates",
            json={
                "challenge_id": start.json()["challenge_id"],
                "challenge_token": start.json()["challenge_token"],
                "credential": credential,
            },
        )
        assert response.status_code == 200, response.text
        return response.json()["candidate_token"]

    def mail_tokens(self, request_id):
        with self.world.storage.transaction() as conn:
            rows = conn.execute(
                "SELECT m.id,m.purpose,m.recipient_digest,m.ciphertext,m.expires_at FROM app.account_mail m JOIN app.auth_challenges c ON c.id=m.challenge_id WHERE c.account_request_id=%s ORDER BY m.purpose",
                (request_id,),
            ).fetchall()
        return {
            row[1]: re.search(
                r"(?:#|&)token=([A-Za-z0-9_-]{43})(?:\n|$)",
                open_job(MailJob(*row, uuid4(), 0), self.passwords.mail_policy)["text"],
            )[1]
            for row in rows
        }


@pytest.fixture
def identity_security(world, monkeypatch):
    return IdentityWorld(world, monkeypatch)
