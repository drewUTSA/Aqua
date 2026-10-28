"""Baseline route and request contracts; new routes require an explicit review."""

import pytest
from fastapi.testclient import TestClient
from fastapi.routing import iter_route_contexts

import main


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
        ("/api/auth/config", "GET"),
        ("/api/auth/google", "POST"),
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
        ("/api/v1/me/preferences", "GET"),
        ("/api/v1/me/preferences", "PUT"),
        ("/api/v1/starter-prompts", "GET"),
    }
    for path in ("/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"):
        expected.update({(path, "GET"), (path, "HEAD")})
    assert actual == expected


@pytest.mark.parametrize("path", ["/api/health", "/api/models"])
def test_public_metadata_remains_uncacheable_without_provider_calls(path):
    response = TestClient(main.app).get(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "cookie" in response.headers["vary"].lower()


def test_query_input_limits_are_part_of_the_contract():
    schema = main.QueryRequest.model_json_schema()
    question = schema["properties"]["question"]
    assert (question["minLength"], question["maxLength"]) == (1, 2000)
    assert schema["required"] == ["question"]
