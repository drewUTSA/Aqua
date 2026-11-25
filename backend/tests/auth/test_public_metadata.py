"""Public liveness is minimal; model choices require a current app session."""

from dataclasses import replace

import main
from nl2sql.config import Settings
from _auth_test_helpers import headers, login


def test_anonymous_health_is_minimal_even_with_private_configuration(
    browser, monkeypatch
):
    client, _, _ = browser
    monkeypatch.setattr(
        main,
        "SETTINGS",
        Settings(ollama_model="synthetic-private-model", retrieval=True),
    )

    def forbidden():
        raise AssertionError("Liveness must not enumerate model choices")

    monkeypatch.setattr(main, "available_models", forbidden)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["cache-control"] == "no-store"


def test_models_refuse_anonymous_and_revoked_sessions_before_enumeration(
    browser, monkeypatch
):
    client, _, _ = browser
    calls = []
    monkeypatch.setattr(main, "available_models", lambda: calls.append(True) or [])
    assert client.get("/api/models").status_code == 401
    assert calls == []
    session = login(browser).json()
    assert (
        client.post(
            "/api/auth/logout", headers=headers(session["csrf_token"])
        ).status_code
        == 204
    )
    assert client.get("/api/models").status_code == 401
    assert calls == []


def test_models_remain_available_to_signed_in_users_without_dataset_grants(
    browser, monkeypatch
):
    client, _, _ = browser
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(main.app.state.settings, auth_allowed_emails=frozenset()),
    )
    monkeypatch.setattr(
        main, "SETTINGS", Settings(ollama_model="synthetic-local-model")
    )
    signed_in = login(browser)
    assert signed_in.status_code == 200 and signed_in.json()["can_query"] is False
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == {
        "models": [
            {
                "id": "ollama",
                "name": "synthetic-local-model",
                "description": "Open model on the team server",
            }
        ]
    }
    assert response.headers["cache-control"] == "no-store"
    assert client.get("/api/health").json() == {"status": "ok"}
