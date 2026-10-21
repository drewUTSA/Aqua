"""Verify session identity, expiration, cookie boundaries, and logout."""

import pytest

from _auth_test_helpers import (
    CLIENT_ID,
    EMAIL,
    challenge,
    forbid_pipeline,
    headers,
    login,
)


def test_login_and_me_return_identity_and_secure_session(browser) -> None:
    client, _, verified = browser
    response = login(browser)
    body = response.json()
    assert body["user"] == {
        "id": body["user"]["id"],
        "email": EMAIL,
        "name": "Aqua Reader",
        "picture": "https://lh3.googleusercontent.com/avatar.png",
    }
    assert body["can_query"] is True and body["csrf_token"]
    assert verified == [("google-id-token", CLIENT_ID)]
    session = next(
        c
        for c in response.headers.get_list("set-cookie")
        if c.startswith("__Host-aqua_session=")
    )
    assert all(
        v in session.lower() for v in ("secure", "httponly", "path=/", "samesite=lax")
    )
    assert "domain=" not in session.lower()
    me = client.get("/api/auth/me")
    assert me.status_code == 200 and me.json() == body
    assert "no-store" in me.headers["cache-control"]


@pytest.mark.parametrize("cookie", [None, "forged.session.value"])
def test_missing_or_forged_session_cannot_query(browser, monkeypatch, cookie) -> None:
    client, _, _ = browser
    called = forbid_pipeline(monkeypatch)
    if cookie:
        client.cookies.set("__Host-aqua_session", cookie, domain="aqua-ai.us", path="/")
    assert client.get("/api/auth/me").status_code == 401
    response = client.post(
        "/api/query", json={"question": "List customers"}, headers=headers("forged")
    )
    assert response.status_code == 401 and called == []


def test_expired_session_cannot_query(browser, monkeypatch, storage) -> None:
    client, _, _ = browser
    body = login(browser).json()
    called = forbid_pipeline(monkeypatch)
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.sessions SET created_at=now()-interval '2 hours', idle_expires_at=now()-interval '1 second', absolute_expires_at=now()-interval '1 second'"
        )
    assert client.get("/api/auth/me").status_code == 401
    response = client.post(
        "/api/query", json={"question": "q"}, headers=headers(body["csrf_token"])
    )
    assert response.status_code == 401 and called == []


def test_login_cookie_cannot_be_used_as_session(browser) -> None:
    client, _, _ = browser
    challenge(browser)
    client.cookies.set(
        "__Host-aqua_session",
        client.cookies.get("__Host-aqua_login"),
        domain="aqua-ai.us",
        path="/",
    )
    assert client.get("/api/auth/me").status_code == 401


def test_logout_requires_csrf_and_clears_session(browser) -> None:
    client, _, _ = browser
    body = login(browser).json()
    assert client.post("/api/auth/logout", headers=headers("forged")).status_code == 403
    assert client.get("/api/auth/me").status_code == 200
    response = client.post("/api/auth/logout", headers=headers(body["csrf_token"]))
    assert response.status_code == 204
    assert response.content == b""
    assert "__Host-aqua_session" not in client.cookies
    assert client.get("/api/auth/me").status_code == 401
