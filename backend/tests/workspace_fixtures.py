"""Real private roles/session checks with a network-free deterministic runner."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from auth.config import load_auth_policy
from auth.sessions import bound_value, new_token, session_cookie_name, token_digest
from auth.store import IdentityStore

GOOD = {
    "status": "success",
    "sql": "SELECT 7",
    "model": "fixture-model",
    "message": "Private fixture answer",
    "tables": [
        {
            "id": "result",
            "title": "Private",
            "columns": [{"key": "value", "label": "Value", "type": "number"}],
            "rows": [{"value": 7}],
        }
    ],
    "visualizations": [],
    "kpis": [],
    "error": None,
}


class World:
    def __init__(self, storage, monkeypatch) -> None:
        self.storage = storage
        self.settings = replace(
            main.app.state.settings,
            database_url="synthetic-workspace",
            app_origin="https://workspace.fixture",
            session_secret="fixture-workspace-secret-" * 3,
            retrieval=False,
            auth_allowed_emails=frozenset(),
            auth_allowed_google_subs=frozenset(),
        )
        self.policy = load_auth_policy(self.settings)
        self.store = IdentityStore(storage, self.policy)
        self.calls = []
        monkeypatch.setattr(main.app.state, "settings", self.settings)
        monkeypatch.setattr(main.app.state, "storage", storage)
        monkeypatch.setattr(main.app.state, "workspace_query", self.answer)

    def answer(self, question, model, session, settings):
        # A leased connection here would exhaust the fixture's one-slot pool.
        with self.storage.transaction() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
        self.calls.append((question, model, session.user["id"]))
        return GOOD.copy()

    def client(self, label="A", *, grant=True):
        raw = new_token()
        csrf = bound_value(self.settings, raw, "session-csrf")
        identity = {
            "sub": "workspace-" + label,
            "email": label.lower() + "@gmail.com",
            "email_verified": True,
            "name": label,
            "picture": "",
        }
        session = self.store.login(
            identity,
            token_digest(raw),
            token_digest(csrf),
            "fixture-peer",
            self.settings,
        )
        if grant:
            with self.storage.transaction() as conn:
                conn.execute(
                    "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s) ON CONFLICT DO NOTHING",
                    (session.user["id"], self.policy.dataset_key),
                )
        client = TestClient(main.app, base_url=self.settings.app_origin)
        client.cookies.set(session_cookie_name(self.settings), raw)
        client.headers.update(
            {"Origin": self.settings.app_origin, "X-CSRF-Token": csrf}
        )
        return client, session.user["id"]

    def body(self, question="Count records", **extra):
        return {"client_request_id": str(uuid4()), "question": question, **extra}

    def submit(self, client, question="Count records"):
        response = client.post("/api/v1/chats", json=self.body(question))
        assert response.status_code == 201, response.text
        return response.json()


@pytest.fixture
def world(storage, monkeypatch):
    return World(storage, monkeypatch)
