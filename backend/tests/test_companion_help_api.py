"""Cookie/CSRF/authority regressions use the existing disposable workspace."""

from types import SimpleNamespace

import pytest

import main
from companion.policy import CompanionPolicy

BASE = "/api/v1/companion"


@pytest.fixture
def enabled(world, monkeypatch):
    monkeypatch.setattr(main.app.state, "companion_policy", CompanionPolicy(True))
    return world


def test_default_off_then_help_without_data_access_never_creates_history(
    world, monkeypatch
):
    client, owner = world.client(grant=False)
    monkeypatch.setattr(main.app.state, "companion_policy", CompanionPolicy())
    assert client.get(BASE + "/capabilities").status_code == 404
    monkeypatch.setattr(main.app.state, "companion_policy", CompanionPolicy(True))
    before = client.get("/api/v1/chats").json()
    menu = client.get(BASE + "/capabilities")
    assert menu.status_code == 200
    assert menu.json()["capabilities"] == [
        {"id": "app_help", "behavior": "reviewed_lookup"}
    ]
    result = client.post(
        BASE + "/help", json={"schemaVersion": 1, "question": "reset password"}
    )
    assert result.status_code == 200 and result.json()["status"] == "answered"
    assert result.json()["citations"][0]["id"] == "password"
    assert client.get("/api/v1/chats").json() == before
    assert client.post("/api/v1/chats", json=world.body()).status_code == 403
    assert (
        result.headers["cache-control"] == "no-store"
        and "cookie" in result.headers["vary"].lower()
    )
    assert owner not in result.text and "fixture-csrf" not in result.text
    assert world.calls == []


def test_advisory_question_choice_reauthorizes_on_existing_submission(enabled):
    client, owner = enabled.client()
    assert {
        v["id"] for v in client.get(BASE + "/capabilities").json()["capabilities"]
    } == {"app_help", "authorized_question"}
    with enabled.storage.transaction() as conn:
        conn.execute("DELETE FROM app.dataset_grants WHERE user_id=%s", (owner,))
    assert client.post("/api/v1/chats", json=enabled.body()).status_code == 403
    assert (
        client.post(
            BASE + "/help", json={"schemaVersion": 1, "question": "charts"}
        ).status_code
        == 200
    )
    assert enabled.calls == []


def test_private_help_denies_extra_duplicate_oversize_or_wrong_content_without_echo(
    enabled,
):
    client, _ = enabled.client()
    bad = [
        {"schemaVersion": True, "question": "SECRET-CANARY"},
        {"schemaVersion": 1, "question": "SECRET-CANARY", "tool": "run_sql"},
        {"schemaVersion": 1, "question": "x" * 2001},
        {"schemaVersion": 1, "question": 123},
    ]
    for value in bad:
        response = client.post(BASE + "/help", json=value)
        assert response.status_code == 422 and "SECRET-CANARY" not in response.text
    response = client.post(
        BASE + "/help",
        content=b'{"schemaVersion":1,"schemaVersion":1,"question":"SECRET-CANARY"}',
        headers={"Content-Type": "application/json"},
    )
    assert response.status_code == 422 and "SECRET-CANARY" not in response.text
    assert (
        client.post(
            BASE + "/help",
            content=b"x" * 16385,
            headers={"Content-Type": "application/json"},
        ).status_code
        == 413
    )
    assert (
        client.post(
            BASE + "/help",
            content="SECRET-CANARY",
            headers={"Content-Type": "text/plain"},
        ).status_code
        == 415
    )
    assert client.get(BASE + "/capabilities?question=SECRET-CANARY").status_code == 422
    assert enabled.calls == []


def test_csrf_revoked_sessions_and_restore_admission_block_help(enabled, monkeypatch):
    client, owner = enabled.client()
    assert (
        client.post(
            BASE + "/help",
            json={"schemaVersion": 1, "question": "charts"},
            headers={"Origin": "https://foreign.invalid"},
        ).status_code
        == 403
    )
    with enabled.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s",
            (owner,),
        )
    assert client.get(BASE + "/capabilities").status_code == 401
    assert (
        client.post(
            BASE + "/help", json={"schemaVersion": 1, "question": "charts"}
        ).status_code
        == 401
    )
    monkeypatch.setattr(
        main.app.state, "retirement", SimpleNamespace(ready=False), raising=False
    )
    response = client.post(
        BASE + "/help", json={"schemaVersion": 1, "question": "charts"}
    )
    assert response.status_code == 503 and response.json() == {
        "error": {"code": "service_unavailable"}
    }
    assert enabled.calls == []


def test_help_and_capability_reads_share_committed_account_admission(enabled):
    client, owner = enabled.client(grant=False)
    for _ in range(30):
        assert client.get(BASE + "/capabilities").status_code == 200
        assert (
            client.post(
                BASE + "/help", json={"schemaVersion": 1, "question": "charts"}
            ).status_code
            == 200
        )
    assert client.get(BASE + "/capabilities").status_code == 429
    with enabled.storage.transaction() as conn:
        assert (
            conn.execute(
                "SELECT hits FROM app.workspace_admission WHERE user_id=%s", (owner,)
            ).fetchone()[0]
            == 60
        )
