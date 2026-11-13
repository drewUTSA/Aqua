"""Redirect transport retains the original durable auth and both CSRF checks."""

import asyncio
from dataclasses import replace

import pytest
from google.auth.exceptions import TransportError

import main
from auth import router
from auth.google_redirect_bridge import document
from _auth_test_helpers import CLIENT_ID
from _durable_route_helpers import CHALLENGE, SESSION, TOKEN, challenge, headers

BASE = "/api/auth/google/redirect"
GOOGLE_CSRF = "synthetic-google-double-submit-token"


def prepare(browser, monkeypatch):
    monkeypatch.setenv("GOOGLE_REDIRECT_ENABLED", "true")
    client, _, _, _ = browser
    config, binding = challenge(browser)
    client.cookies.set("g_csrf_token", GOOGLE_CSRF)
    body = {"credential": TOKEN, "g_csrf_token": GOOGLE_CSRF, "client_id": CLIENT_ID}
    return client, config, binding, body


def test_default_off_and_https_required(durable_browser, monkeypatch):
    client, _, verified, _ = durable_browser
    monkeypatch.delenv("GOOGLE_REDIRECT_ENABLED", raising=False)
    config, _ = challenge(durable_browser)
    assert "redirect_path" not in config
    assert client.post(BASE, json={}).status_code == 404
    assert client.get(BASE + "-state").status_code == 404
    assert client.post(BASE + "-complete", json={}).status_code == 404
    monkeypatch.setenv("GOOGLE_REDIRECT_ENABLED", "true")
    monkeypatch.setattr(
        main.app.state,
        "settings",
        replace(main.app.state.settings, app_origin="http://localhost:5173"),
    )
    assert client.get("/api/auth/config").status_code == 503
    assert verified == []


@pytest.mark.parametrize("encoding", ["json", "form"])
@pytest.mark.parametrize(
    "initial_origin", ["https://accounts.google.com", "null", None]
)
def test_cross_site_document_is_inert_then_first_party_completion_is_one_use(
    durable_browser, monkeypatch, encoding, caplog, initial_origin
):
    client, config, binding, body = prepare(durable_browser, monkeypatch)
    assert config["redirect_path"] == BASE
    caplog.set_level("INFO")
    kwargs = {"json": body} if encoding == "json" else {"data": body}
    # Model a cross-site POST omitting both existing Lax cookies. It renders no
    # authority: the same cookies must return on the first-party requests.
    initial_headers = {"Cookie": ""}
    if initial_origin is not None:
        initial_headers["Origin"] = initial_origin
    page = client.post(BASE, headers=initial_headers, **kwargs)
    assert page.status_code == 200
    assert page.headers["cache-control"] == "no-store"
    assert page.headers["referrer-policy"] == "no-referrer"
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert "set-cookie" not in page.headers
    assert client.cookies.get(CHALLENGE) == binding
    _, _, verified, storage = durable_browser
    assert verified == []
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE consumed_at IS NOT NULL"
        ).fetchone() == (0,)
    state = client.get(BASE + "-state")
    assert state.status_code == 200 and state.json() == {
        "csrf_token": config["csrf_token"]
    }
    assert "set-cookie" not in state.headers
    original = router.verify_google_token

    def verify(*args):
        with pytest.raises(RuntimeError):
            asyncio.get_running_loop()  # Provider I/O must stay off the event loop.
        return original(*args)

    monkeypatch.setattr(router, "verify_google_token", verify)
    result = client.post(
        BASE + "-complete", json=body, headers=headers(config["csrf_token"])
    )
    assert result.status_code == 200 and len(verified) == 1
    assert client.get("/api/auth/me").status_code == 200
    cookie = result.headers["set-cookie"]
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=lax" in cookie
    assert "Domain=" not in cookie
    assert (
        client.post(
            BASE + "-complete", json=body, headers=headers(config["csrf_token"])
        ).status_code
        == 403
    )
    assert len(verified) == 1
    assert TOKEN not in caplog.text and GOOGLE_CSRF not in caplog.text


@pytest.mark.parametrize(
    "attack",
    [
        "google_missing",
        "google_mismatch",
        "origin_missing",
        "origin_foreign",
        "origin_null",
        "header_missing",
        "header_wrong",
        "google_duplicate",
        "challenge_duplicate",
    ],
)
def test_csrf_denial_precedes_consumption_and_provider(
    durable_browser, monkeypatch, attack
):
    client, config, binding, body = prepare(durable_browser, monkeypatch)
    outgoing = headers(config["csrf_token"])
    if attack == "google_missing":
        client.cookies.delete("g_csrf_token")
    elif attack == "google_mismatch":
        body["g_csrf_token"] += "different"
    elif attack == "origin_missing":
        outgoing.pop("Origin")
    elif attack == "origin_foreign":
        outgoing["Origin"] = "https://attacker.example"
    elif attack == "origin_null":
        outgoing["Origin"] = "null"
    elif attack == "header_missing":
        outgoing.pop("X-CSRF-Token")
    elif attack == "header_wrong":
        outgoing["X-CSRF-Token"] = "wrong"
    else:
        duplicate = "g_csrf_token" if attack == "google_duplicate" else CHALLENGE
        outgoing["Cookie"] = (
            f"g_csrf_token={GOOGLE_CSRF}; {CHALLENGE}={binding}; {duplicate}=different"
        )
    response = client.post(BASE + "-complete", json=body, headers=outgoing)
    assert response.status_code == 403
    _, _, verified, storage = durable_browser
    assert verified == [] and SESSION not in client.cookies
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE consumed_at IS NOT NULL"
        ).fetchone() == (0,)


@pytest.mark.parametrize("attack", ["nonce", "provider", "expired"])
def test_original_nonce_provider_and_expiry_fail_closed(
    durable_browser, monkeypatch, attack
):
    client, config, _, body = prepare(durable_browser, monkeypatch)
    _, claims, verified, storage = durable_browser
    if attack == "nonce":
        claims["nonce"] = "wrong"
    elif attack == "provider":

        def unavailable(*args):
            raise TransportError("private-provider-diagnostic")

        monkeypatch.setattr(router, "verify_google_token", unavailable)
    else:
        with storage.transaction() as conn:
            conn.execute(
                "UPDATE app.auth_challenges SET created_at=clock_timestamp()-interval '20 minutes',expires_at=clock_timestamp()-interval '1 second'"
            )
    response = client.post(
        BASE + "-complete", json=body, headers=headers(config["csrf_token"])
    )
    assert (
        response.status_code == {"nonce": 401, "provider": 503, "expired": 403}[attack]
    )
    assert "private-provider-diagnostic" not in response.text
    assert SESSION not in client.cookies
    assert len(verified) == (1 if attack == "nonce" else 0)
    assert (
        client.post(
            BASE + "-complete", json=body, headers=headers(config["csrf_token"])
        ).status_code
        == 403
    )


def test_bridge_escapes_script_text_and_nonce_is_response_local():
    canary = '</script><script>alert("PRIVATE")</script>&'
    html, first = document({"credential": canary, "g_csrf_token": "NONCE-PAYLOAD"})
    other, second = document({"credential": "other", "g_csrf_token": "token"})
    assert canary not in html and html.count("</script>") == 1
    assert "\\u003c/script\\u003e" in html
    assert "document.currentScript.remove()" in html
    assert first["Content-Security-Policy"] != second["Content-Security-Policy"]
    assert "location.replace('/')" in html and "attacker.example" not in other
    assert "localStorage" not in html and "sessionStorage" not in html
