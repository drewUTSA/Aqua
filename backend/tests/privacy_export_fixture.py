"""Real disposable roles/proofs, manual export ticks, and zero real providers."""

import hashlib
import json
from dataclasses import replace
from uuid import uuid4

import anyio
import main
import pytest

from privacy.contracts import ExportCreate
from privacy import policy
from privacy.service import ExportService
from privacy.worker import Worker
from security_action_fixtures import OLD, PATH

EXPORTS = PATH + "/data-exports"


class PrivacyWorld:
    def __init__(self, secure, monkeypatch):
        self.secure, self.world = secure, secure.world
        self.world.analysis.settings = self.world.settings
        # This explicit synthetic fixture has one web process and no preopened
        # web pool. Use production's four-connection budget while leaving all
        # earlier one-slot P10 fixtures unchanged. Only process argv is modeled;
        # this fixture cannot certify actual deployment/container topology.
        assert self.world.storage._pool is None
        self.world.storage.settings = replace(
            self.world.storage.settings, max_connections=4
        )
        monkeypatch.setenv(policy.ACTIVATION_FLAG, "true")
        monkeypatch.setenv("WEB_CONCURRENCY", "1")
        monkeypatch.setenv("UVICORN_WORKERS", "1")
        monkeypatch.setattr(
            policy, "runtime_context", lambda argv, *, child=False: not child
        )
        # P11 tests exercise real 5/account and 30/global proof admission. The
        # broader old identity fixture's raised budgets do not apply here.
        self.secure.passwords.auth_policy = self.world.policy
        assert self.world.policy.action_account_limit == 5
        assert self.world.policy.action_global_limit == 30
        self.service = ExportService(
            self.world.storage, self.world.policy, self.world.settings, start=False
        )
        assert self.service.configured
        monkeypatch.setattr(main.app.state, "privacy", self.service, raising=False)
        self.worker = Worker(self.service)

    def client(self, label="A", *, linked=True, grant=False):
        client, owner = self.secure.client(label, linked=linked)
        if grant:
            with self.world.storage.transaction() as conn:
                conn.execute(
                    "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (owner, self.world.policy.dataset_key),
                )
        return client, owner

    def proof(self, client, intent, *, google=False):
        target = {"operation": "data_export", "target_intent_id": intent}
        if google:
            principal = self.secure.principal(client)
            with self.world.storage.transaction() as conn:
                identity, subject, email = conn.execute(
                    "SELECT id,subject,observed_email_key FROM app.external_identities WHERE user_id=%s AND is_active ORDER BY id LIMIT 1",
                    (principal.user["id"],),
                ).fetchone()
            start = client.post(
                PATH + "/reauth/google-challenges",
                json={**target, "identity_id": str(identity)},
            )
            assert start.status_code == 200, start.text
            credential = self.secure.assertion(
                start.json()["nonce"], subject=subject, email=email
            )
            verified = client.post(
                PATH + "/reauth/google",
                json={
                    **target,
                    "challenge_id": start.json()["challenge_id"],
                    "challenge_token": start.json()["challenge_token"],
                    "credential": credential,
                },
            )
        else:
            start = client.post(PATH + "/reauth-challenges", json=target)
            assert start.status_code == 200, start.text
            verified = client.post(
                PATH + "/reauth/password",
                json={
                    **target,
                    "challenge_id": start.json()["challenge_id"],
                    "challenge_token": start.json()["challenge_token"],
                    "password": OLD,
                },
            )
        assert verified.status_code == 200, verified.text
        return verified.json()["proof_token"]

    def queue(self, client, *, intent=None, google=False):
        intent = intent or str(uuid4())
        proof = self.proof(client, intent, google=google)
        body = {"intent_id": intent, "scope": "personal_v1", "proof_token": proof}
        response = client.post(EXPORTS, json=body)
        assert response.status_code == 202, response.text
        assert response.json()["job"]["state"] == "queued"
        return response.json()["job"], body

    def bytes(self, owner, job_id):
        with self.world.storage.transaction() as conn:
            rows = conn.execute(
                "SELECT body FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s ORDER BY generation,ordinal",
                (owner, job_id),
            ).fetchall()
        return b"".join(bytes(row[0]) for row in rows)

    def ready(self, client, owner, **kwargs):
        job, body = self.queue(client, **kwargs)
        assert self.worker.once()
        response = client.get(EXPORTS + "/" + job["id"])
        assert response.status_code == 200, response.text
        ready = response.json()["job"]
        assert ready["state"] == "ready", response.text
        raw = self.bytes(owner, job["id"])
        assert ready["byte_count"] == len(raw)
        assert ready["sha256"] == hashlib.sha256(raw).hexdigest()
        json.loads(raw)
        return ready, raw, body

    def creation(self, client, body):
        return self.service.create(
            self.secure.principal(client),
            ExportCreate.model_validate(body),
            self.secure.passwords,
        )


@pytest.fixture
def private_exports(identity_security, monkeypatch):
    fixture = PrivacyWorld(identity_security, monkeypatch)
    try:
        yield fixture
    finally:
        anyio.run(fixture.service.aclose)
