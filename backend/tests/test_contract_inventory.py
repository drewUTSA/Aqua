"""Baseline route and request contracts; new routes require an explicit review."""

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import iter_route_contexts

import main
from nl2sql.config import Settings


def test_current_http_surface_is_explicit():
    actual = {
        (route.path, method)
        for route in iter_route_contexts(main.app.routes)
        for method in (route.methods or ())
    }
    expected = {
        ("/api/health", "GET"),
        ("/api/ready", "GET"),
        ("/api/models", "GET"),
        ("/api/query", "POST"),
        ("/api/v1/analysis-requests/{request_id}", "GET"),
        ("/api/v1/analysis-requests/{request_id}/cancel", "POST"),
        ("/api/v1/analysis-requests/{request_id}/events", "GET"),
        ("/api/v1/companion/capabilities", "GET"),
        ("/api/v1/companion/help", "POST"),
        ("/api/v1/companion/result-brief", "POST"),
        ("/api/v1/bank-demo/context", "GET"),
        ("/api/v1/bank-demo/reports", "POST"),
        ("/api/v1/bank-demo/calculations", "POST"),
        ("/api/auth/config", "GET"),
        ("/api/auth/google", "POST"),
        ("/api/auth/google/redirect", "POST"),
        ("/api/auth/google/redirect-state", "GET"),
        ("/api/auth/google/redirect-complete", "POST"),
        ("/api/auth/me", "GET"),
        ("/api/auth/logout", "POST"),
        ("/api/v1/auth/bootstrap", "GET"),
        ("/api/v1/auth/registrations", "POST"),
        ("/api/v1/auth/email-verifications", "POST"),
        ("/api/v1/auth/password-login", "POST"),
        ("/api/v1/auth/password-reset-requests", "POST"),
        ("/api/v1/auth/password-resets", "POST"),
        ("/api/v1/chats", "GET"),
        ("/api/v1/chats", "POST"),
        ("/api/v1/chats/search", "POST"),
        ("/api/v1/chats/{chat_id}", "GET"),
        ("/api/v1/chats/{chat_id}", "PATCH"),
        ("/api/v1/chats/{chat_id}", "DELETE"),
        ("/api/v1/chats/{chat_id}/messages", "GET"),
        ("/api/v1/chats/{chat_id}/messages/{message_id}/previous-source", "GET"),
        ("/api/v1/chats/{chat_id}/messages", "POST"),
        ("/api/v1/chats/{chat_id}/messages/{input_id}/retries", "POST"),
        ("/api/v1/projects", "GET"),
        ("/api/v1/projects", "POST"),
        ("/api/v1/projects/{item_id}", "PATCH"),
        ("/api/v1/projects/{item_id}", "DELETE"),
        ("/api/v1/me/saved-prompts", "GET"),
        ("/api/v1/me/saved-prompts", "POST"),
        ("/api/v1/me/saved-prompts/{item_id}", "PATCH"),
        ("/api/v1/me/saved-prompts/{item_id}", "DELETE"),
        ("/api/v1/me/saved-prompts/{item_id}/uses", "POST"),
        ("/api/v1/me/context-notes", "GET"),
        ("/api/v1/me/context-notes", "POST"),
        ("/api/v1/me/context-notes/{note_id}", "GET"),
        ("/api/v1/me/context-notes/{note_id}", "PATCH"),
        ("/api/v1/me/context-notes/{note_id}/forget", "POST"),
        ("/api/v1/me/context-notes/{note_id}/prepare", "POST"),
        ("/api/v1/me/preferences", "GET"),
        ("/api/v1/me/preferences", "PUT"),
        ("/api/v1/me", "GET"),
        ("/api/v1/me", "PATCH"),
        ("/api/v1/me/methods", "GET"),
        ("/api/v1/me/sessions", "GET"),
        ("/api/v1/me/reauth-challenges", "POST"),
        ("/api/v1/me/reauth/password", "POST"),
        ("/api/v1/me/password", "PUT"),
        ("/api/v1/me/sessions/{session_id}/revocations", "POST"),
        ("/api/v1/me/session-revocations", "POST"),
        ("/api/v1/me/reauth/google-challenges", "POST"),
        ("/api/v1/me/reauth/google", "POST"),
        ("/api/v1/me/google-link-challenges", "POST"),
        ("/api/v1/me/google-link-candidates", "POST"),
        ("/api/v1/me/google-links", "POST"),
        ("/api/v1/me/methods/google/{identity_id}/revocations", "POST"),
        ("/api/v1/me/password-enrollments", "POST"),
        ("/api/v1/me/password", "POST"),
        ("/api/v1/me/email-change-requests", "POST"),
        ("/api/v1/me/email", "PUT"),
        ("/api/v1/me/data-exports", "GET"),
        ("/api/v1/me/data-exports", "POST"),
        ("/api/v1/me/data-exports/by-intent/{intent_id}", "GET"),
        ("/api/v1/me/data-exports/{job_id}", "GET"),
        ("/api/v1/me/data-exports/{job_id}/download", "GET"),
        ("/api/v1/me/data-deletions", "POST"),
        ("/api/v1/me/data-deletions/by-intent/{intent_id}", "POST"),
        ("/api/v1/me/notification-settings", "GET"),
        ("/api/v1/me/notification-settings", "PUT"),
        ("/api/v1/starter-prompts", "GET"),
    }
    for path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
        expected.update({(path, "GET"), (path, "HEAD")})
    assert actual == expected


@pytest.mark.parametrize("path,status", [("/api/health", 200), ("/api/models", 503)])
def test_metadata_remains_uncacheable_without_provider_calls(monkeypatch, path, status):
    # Liveness remains public during configuration failure; model enumeration
    # must fail closed. Configured anonymous/session cases use the auth fixture.
    monkeypatch.setattr(main.app.state, "settings", Settings(session_secret=""))

    def forbidden():
        raise AssertionError("Metadata must not enumerate models without a session")

    monkeypatch.setattr(main, "available_models", forbidden)
    response = TestClient(main.app).get(path)
    assert response.status_code == status
    assert response.headers["cache-control"] == "no-store"
    assert "cookie" in response.headers["vary"].lower()


def test_query_input_limits_are_part_of_the_contract():
    schema = main.QueryRequest.model_json_schema()
    question = schema["properties"]["question"]
    assert (question["minLength"], question["maxLength"]) == (1, 2000)
    assert schema["required"] == ["question"]
