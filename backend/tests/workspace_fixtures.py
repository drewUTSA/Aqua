"""Real private roles/session checks with a network-free deterministic runner."""

from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import main
from auth.config import load_auth_policy
from auth.sessions import bound_value, new_token, session_cookie_name, token_digest
from auth.store import IdentityStore
from auth.security import UserSession
from analysis.service import Analysis
from workspace.completion import execute

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
        self.sessions = {}
        monkeypatch.setattr(main.app.state, "settings", self.settings)
        monkeypatch.setattr(main.app.state, "storage", storage)
        monkeypatch.setattr(main.app.state, "workspace_query", self.answer)
        self.analysis = Analysis(
            storage,
            self.policy,
            self.settings.session_secret,
            self.settings,
            engine=WorldEngine(self),
        )
        monkeypatch.setattr(main.app.state, "analysis", self.analysis, raising=False)

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
        stored = self.store.authenticate(token_digest(raw), meaningful_activity=False)
        self.sessions[session.user["id"]] = UserSession(
            stored.user,
            csrf,
            token_digest(raw),
            stored.can_query,
            stored.grant_version,
            stored.auth_epoch,
            stored.dataset_key,
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
        assert response.status_code == 202, response.text
        self.analysis.tick()
        saved = client.get(
            "/api/v1/analysis-requests/" + response.json()["request"]["id"]
        )
        assert saved.status_code == 200, saved.text
        return saved.json()


class WorldEngine:
    """Existing workspace regressions use genuine queued HTTP then an explicit tick."""

    def __init__(self, world):
        self.world = world

    def run(self, payload, control):
        control("generating")
        response = execute(
            main.app.state.workspace_query,
            payload["question"],
            payload["model"],
            self.world.sessions[payload["principal"]],
            self.world.settings,
        )
        return response, 200

    def close(self):
        pass


@pytest.fixture
def world(storage, monkeypatch):
    instance = World(storage, monkeypatch)
    try:
        yield instance
    finally:
        instance.analysis.close()
