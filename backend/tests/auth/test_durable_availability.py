"""Exercise durable browser boundaries without external identity calls."""

from contextlib import contextmanager
from dataclasses import replace
import pytest
import main
from storage.pool import StorageUnavailable
from _auth_test_helpers import forbid_pipeline
from _durable_route_helpers import (
    SESSION,
    CHALLENGE,
    TOKEN,
    headers,
    challenge,
    login,
)


@pytest.mark.parametrize(
    "path",
    [
        "/api/auth/me",
        "/api/auth/logout",
        "/api/query",
        "/api/auth/config",
        "/api/auth/google",
    ],
)
def test_storage_outage_never_falls_back_or_reports_logout_success(
    durable_browser, monkeypatch, path
):
    client, _, verified, storage = durable_browser
    payload, cookie = login(durable_browser)
    pending, challenge_cookie = challenge(durable_browser)
    called = forbid_pipeline(monkeypatch)

    @contextmanager
    def unavailable():
        raise StorageUnavailable("PRIVATE_DATABASE_CONNECTION_CANARY")
        yield

    monkeypatch.setattr(storage, "transaction", unavailable)
    request_headers = headers(payload["csrf_token"])
    if path == "/api/auth/google":
        request_headers = headers(pending["csrf_token"], challenge_cookie, CHALLENGE)
    if path in {"/api/auth/me", "/api/auth/config"}:
        response = client.get(path)
    else:
        response = client.post(
            path,
            json=(
                {"credential": TOKEN} if path.endswith("google") else {"question": "q"}
            ),
            headers=request_headers,
        )
    assert response.status_code == 503
    assert "PRIVATE_DATABASE_CONNECTION_CANARY" not in response.text
    assert TOKEN not in response.text and called == [] and verified == [True]
    if path == "/api/auth/logout":
        assert client.cookies.get(SESSION) == cookie
        assert "set-cookie" not in response.headers


def test_authenticated_account_without_dataset_is_not_an_authentication_failure(
    durable_browser, monkeypatch
):
    client, _, _, _ = durable_browser
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(main.app.state.settings, auth_allowed_emails=frozenset()),
    )
    payload, _ = login(durable_browser)
    assert payload["user"]["id"] and payload["can_query"] is False
    called = forbid_pipeline(monkeypatch)
    assert client.get("/api/auth/me").status_code == 200
    response = client.post(
        "/api/query",
        json={"question": "q"},
        headers=headers(payload["csrf_token"]),
    )
    assert response.status_code == 403 and called == []


def test_google_configuration_loss_does_not_invalidate_existing_app_session(
    durable_browser, monkeypatch
):
    client, _, _, _ = durable_browser
    payload, _ = login(durable_browser)
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(main.app.state.settings, google_client_id=""),
    )
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/auth/config").status_code == 503
    assert (
        client.post(
            "/api/auth/logout", headers=headers(payload["csrf_token"])
        ).status_code
        == 204
    )


def test_logout_commit_failure_preserves_cookie_and_actual_session(
    durable_browser, monkeypatch, caplog
):
    client, _, _, storage = durable_browser
    payload, cookie = login(durable_browser)
    original_transaction = storage.transaction
    calls = []
    caplog.set_level("INFO", logger="aqua.auth")

    @contextmanager
    def fail_revocation_commit():
        calls.append(True)
        with original_transaction() as conn:
            yield conn
            if len(calls) == 2:
                # Lookup/activity committed, then the real UPDATE executes but
                # its transaction rolls back instead of confirming revocation.
                raise StorageUnavailable("PRIVATE_AUTH_TRANSACTION_CANARY")

    monkeypatch.setattr(storage, "transaction", fail_revocation_commit)
    response = client.post("/api/auth/logout", headers=headers(payload["csrf_token"]))
    assert response.status_code == 503 and len(calls) == 2
    assert (
        client.cookies.get(SESSION) == cookie and "set-cookie" not in response.headers
    )
    assert "auth_event action=deny reason=logout_unavailable" in caplog.messages
    assert "PRIVATE_AUTH_TRANSACTION_CANARY" not in response.text + caplog.text
    assert client.get("/api/auth/me").status_code == 200
