"""Exercise durable browser boundaries without external identity calls."""

from fastapi.testclient import TestClient
from itsdangerous import URLSafeTimedSerializer
import pytest
import main
from _auth_test_helpers import EMAIL, SUBJECT, ORIGIN, forbid_pipeline
from _durable_route_helpers import (
    SESSION,
    TOKEN,
    challenge,
    headers,
    login,
)


def test_legacy_signed_session_is_rejected_before_query_work(
    durable_browser, monkeypatch
):
    client, _, _, _ = durable_browser
    called = forbid_pipeline(monkeypatch)
    legacy = URLSafeTimedSerializer(
        main.app.state.settings.session_secret, salt="aqua-session-v1"
    ).dumps(
        {
            "user": {"sub": SUBJECT, "email": EMAIL, "email_verified": True},
            "csrf_token": "old",
        }
    )
    assert (
        client.get(
            "/api/auth/me", headers={"Cookie": f"{SESSION}={legacy}"}
        ).status_code
        == 401
    )
    result = client.post(
        "/api/query", json={"question": "q"}, headers=headers("old", legacy)
    )
    assert result.status_code == 401 and called == []


def test_copied_cookie_is_revoked_durably_by_logout(durable_browser, caplog):
    caplog.set_level("INFO", logger="aqua.auth")
    client, _, _, _ = durable_browser
    payload, cookie = login(durable_browser)
    copied = TestClient(main.app, base_url=ORIGIN)
    assert (
        copied.get(
            "/api/auth/me", headers={"Cookie": f"{SESSION}={cookie}"}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/auth/logout", headers=headers(payload["csrf_token"])
        ).status_code
        == 204
    )
    assert (
        copied.get(
            "/api/auth/me", headers={"Cookie": f"{SESSION}={cookie}"}
        ).status_code
        == 401
    )
    assert "auth_event action=allow reason=session_created" in caplog.messages
    assert "auth_event action=allow reason=session_revoked" in caplog.messages
    assert cookie not in caplog.text


@pytest.mark.parametrize("change", ["epoch", "disabled", "revoked"])
def test_account_or_session_fencing_denies_before_pipeline(
    durable_browser, monkeypatch, change
):
    client, _, _, storage = durable_browser
    payload, _ = login(durable_browser)
    called = forbid_pipeline(monkeypatch)
    with storage.transaction() as conn:
        if change == "epoch":
            conn.execute("UPDATE app.users SET auth_epoch=auth_epoch+1")
        elif change == "disabled":
            conn.execute("UPDATE app.users SET status='disabled'")
        else:
            conn.execute("UPDATE app.sessions SET revoked_at=clock_timestamp()")
    assert client.get("/api/auth/me").status_code == 401
    result = client.post(
        "/api/query", json={"question": "q"}, headers=headers(payload["csrf_token"])
    )
    assert result.status_code == 401 and called == []


def test_revoked_dataset_grant_does_not_resurrect_on_relogin(
    durable_browser, monkeypatch
):
    client, _, _, storage = durable_browser
    payload, _ = login(durable_browser)
    assert payload["can_query"] is True
    called = forbid_pipeline(monkeypatch)
    with storage.transaction() as conn:
        conn.execute("UPDATE app.dataset_grants SET revoked_at=clock_timestamp()")
    response = client.get("/api/auth/me")
    assert response.status_code == 200 and response.json()["can_query"] is False
    assert (
        client.post(
            "/api/query", json={"question": "q"}, headers=headers(payload["csrf_token"])
        ).status_code
        == 403
    )
    renewed, _ = login(durable_browser)
    assert renewed["can_query"] is False and called == []
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.dataset_grants WHERE revoked_at IS NULL"
        ).fetchone() == (0,)


def test_login_rotates_cookie_and_csrf_without_accepting_cross_session_token(
    durable_browser, monkeypatch
):
    client, _, _, _ = durable_browser
    first, old_cookie = login(durable_browser)
    second, new_cookie = login(durable_browser)
    assert old_cookie != new_cookie and first["csrf_token"] != second["csrf_token"]
    called = forbid_pipeline(monkeypatch)
    response = client.post(
        "/api/query", json={"question": "q"}, headers=headers(first["csrf_token"])
    )
    assert response.status_code == 403 and called == []
    assert (
        client.post(
            "/api/auth/logout", headers=headers(first["csrf_token"])
        ).status_code
        == 403
    )
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json()["csrf_token"] == second["csrf_token"]


def test_equal_verified_email_never_links_a_different_google_subject(durable_browser):
    client, claims, _, storage = durable_browser
    first, _ = login(durable_browser)
    client.cookies.clear()
    claims["sub"] = "different-synthetic-google-subject"
    pending, _ = challenge(durable_browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": TOKEN},
        headers=headers(pending["csrf_token"]),
    )
    assert response.status_code == 401 and SESSION not in client.cookies
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (1,)
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (1,)
        assert conn.execute(
            "SELECT user_id::text FROM app.external_identities"
        ).fetchone() == (first["user"]["id"],)


def test_caller_selected_session_cookie_is_replaced_on_login(durable_browser):
    client, _, _, storage = durable_browser
    selected = "v2." + "A" * 43
    client.cookies.set(SESSION, selected, domain="aqua-ai.us", path="/")
    _, issued = login(durable_browser)
    assert issued != selected
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (1,)
