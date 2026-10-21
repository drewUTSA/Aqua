"""Exercise durable browser boundaries without external identity calls."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
from fastapi.testclient import TestClient
from google.auth.exceptions import TransportError
import pytest
import main
from auth import router, security
from _auth_test_helpers import ORIGIN
from _durable_route_helpers import (
    SESSION,
    CHALLENGE,
    TOKEN,
    headers,
    challenge,
    login,
)


@pytest.mark.parametrize("parallel", [False, True])
def test_copied_challenge_has_one_provider_call_and_one_session(
    durable_browser, parallel, caplog
):
    caplog.set_level("INFO", logger="aqua.auth")
    _, _, verified, storage = durable_browser
    payload, cookie = challenge(durable_browser)
    # Prove durable compare-and-consume, without conflating cold pool creation
    # with admission: one established connection plus one waiter stays bounded.
    assert storage.readiness()["application_storage"] == "ready"
    gate = threading.Barrier(2) if parallel else None

    def submit():
        copied = TestClient(main.app, base_url=ORIGIN)
        if gate:
            gate.wait(timeout=5)
        return copied.post(
            "/api/auth/google",
            json={"credential": TOKEN},
            headers=headers(payload["csrf_token"], cookie, CHALLENGE),
        ).status_code

    if parallel:
        with ThreadPoolExecutor(max_workers=2) as workers:
            results = list(workers.map(lambda _: submit(), range(2)))
    else:
        results = [submit(), submit()]
    assert sorted(results) == [200, 403] and verified == [True]
    assert "auth_event action=allow reason=session_created" in caplog.messages
    assert "auth_event action=deny reason=challenge_invalid" in caplog.messages
    assert TOKEN not in caplog.text and cookie not in caplog.text
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE consumed_at IS NOT NULL"
        ).fetchone() == (1,)


def test_provider_outage_consumes_challenge_without_creating_identity(
    durable_browser, monkeypatch, caplog
):
    caplog.set_level("INFO", logger="aqua.auth")
    client, _, _, storage = durable_browser
    payload, cookie = challenge(durable_browser)
    calls = []

    def unavailable(*args):
        calls.append(True)
        raise TransportError("PRIVATE_GOOGLE_CONNECTION_CANARY")

    monkeypatch.setattr(router, "verify_google_token", unavailable)
    request_headers = headers(payload["csrf_token"], cookie, CHALLENGE)
    first = client.post(
        "/api/auth/google", json={"credential": TOKEN}, headers=request_headers
    )
    assert (
        first.status_code == 503
        and "PRIVATE_GOOGLE_CONNECTION_CANARY" not in first.text
    )
    assert (
        client.post(
            "/api/auth/google", json={"credential": TOKEN}, headers=request_headers
        ).status_code
        == 403
    )
    assert calls == [True]
    assert "auth_event action=deny reason=provider_unavailable" in caplog.messages
    assert "auth_event action=deny reason=challenge_invalid" in caplog.messages
    assert "PRIVATE_GOOGLE_CONNECTION_CANARY" not in caplog.text
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.users").fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)


def test_no_raw_session_challenge_or_google_values_in_public_identity_or_logs(
    durable_browser, caplog
):
    caplog.set_level("INFO", logger="aqua.auth")
    client, _, _, _ = durable_browser
    payload, challenge_cookie = challenge(durable_browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": TOKEN},
        headers=headers(payload["csrf_token"]),
    )
    assert response.status_code == 200
    session_cookie = client.cookies.get(SESSION)
    public = response.json()
    assert set(public["user"]) == {"id", "email", "name", "picture"}
    for secret in (TOKEN, session_cookie, challenge_cookie):
        assert secret not in response.text and secret not in caplog.text
    assert "no-store" in response.headers["cache-control"]


def test_login_budget_precedes_provider_and_survives_cookie_and_header_churn(
    durable_browser, monkeypatch
):
    client, _, verified, storage = durable_browser
    original_policy = security.load_auth_policy
    monkeypatch.setattr(
        security,
        "load_auth_policy",
        lambda settings: replace(original_policy(settings), login_peer_limit=1),
    )
    login(durable_browser)
    client.cookies.clear()
    pending, _ = challenge(durable_browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": TOKEN},
        headers={
            **headers(pending["csrf_token"]),
            "X-Forwarded-For": "198.51.100.77",
            "CF-Connecting-IP": "203.0.113.99",
            "Forwarded": "for=192.0.2.123",
        },
    )
    assert response.status_code == 429 and verified == [True]
    assert 1 <= int(response.headers["retry-after"]) <= 60
    with storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (1,)
        conn.execute(
            "UPDATE app.auth_admission SET expires_at=clock_timestamp()-interval '1 second'"
        )
    assert login(durable_browser)[0]["can_query"] is True
    assert verified == [True, True]


@pytest.mark.parametrize(
    "credential", [TOKEN * 300, {"nested_secret": TOKEN}], ids=["oversized", "nested"]
)
def test_malformed_credential_validation_never_reflects_secret(
    durable_browser, credential, caplog
):
    client, _, verified, _ = durable_browser
    pending, _ = challenge(durable_browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": credential},
        headers=headers(pending["csrf_token"]),
    )
    assert response.status_code == 422 and verified == []
    assert TOKEN not in response.text and TOKEN not in caplog.text
    assert "no-store" in response.headers["cache-control"]
