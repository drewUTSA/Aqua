"""Attack browser identity transitions against disposable PostgreSQL only."""

from dataclasses import replace


from fastapi.testclient import TestClient


import pytest

import main

from auth import router, security
from storage.pool import Storage
from legacy_contract_fixture import install


from _auth_test_helpers import CLIENT_ID, EMAIL, ORIGIN, SUBJECT

SESSION = "__Host-aqua_session"

CHALLENGE = "__Host-aqua_login"

TOKEN = "PRIVATE_GOOGLE_TOKEN_ROUTE_CANARY"


def headers(csrf: str, cookie: str = "", name: str = SESSION) -> dict[str, str]:
    result = {"Origin": ORIGIN, "X-CSRF-Token": csrf}
    if cookie:
        result["Cookie"] = f"{name}={cookie}"
    return result


@pytest.fixture
def durable_browser(storage, monkeypatch):
    """Each attack receives a fresh schema and a fake Google transport."""
    # Two callbacks traverse consume/reserve/account transactions and may queue
    # behind reset work. Keep one connection to prove provider lease release,
    # with four bounded waiters so this tests replay rather than queue overload.
    # The separate storage fixture's one-waiter saturation tests stay unchanged.
    storage = Storage(replace(storage.settings, max_waiting=4))
    original_policy = security.load_auth_policy
    monkeypatch.setattr(
        security,
        "load_auth_policy",
        lambda settings: replace(
            original_policy(settings),
            challenge_peer_limit=300,
            challenge_global_limit=300,
            login_peer_limit=300,
            login_global_limit=300,
            login_account_limit=300,
        ),
    )
    settings = replace(
        main.app.state.settings,
        google_client_id=CLIENT_ID,
        session_secret="durable-route-test-secret-" * 3,
        app_origin=ORIGIN,
        auth_allowed_emails=frozenset({EMAIL}),
        auth_allowed_google_subs=frozenset(),
    )
    monkeypatch.setattr(main.app.state, "settings", settings)
    monkeypatch.setattr(main.app.state, "storage", storage)
    # Dataset/model tests patch the shared query service in this process;
    # authentication and current-dataset authorization remain real DB work.
    install(monkeypatch)
    claims = {
        "iss": "https://accounts.google.com",
        "sub": SUBJECT,
        "email": EMAIL,
        "email_verified": True,
        "name": "Synthetic reader",
    }
    verified = []

    def verify(credential, client_id):
        assert credential == TOKEN and client_id == CLIENT_ID
        # The sole pool connection must be free while an external call runs.
        with storage.transaction() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
        verified.append(True)
        return claims.copy()

    monkeypatch.setattr(router, "verify_google_token", verify)
    with TestClient(main.app, base_url=ORIGIN) as client:
        yield client, claims, verified, storage


def challenge(browser):
    client, claims, _, _ = browser
    response = client.get("/api/auth/config")
    assert response.status_code == 200
    payload = response.json()
    claims["nonce"] = payload["nonce"]
    return payload, client.cookies.get(CHALLENGE)


def login(browser):
    client, _, _, _ = browser
    payload, _ = challenge(browser)
    response = client.post(
        "/api/auth/google",
        json={"credential": TOKEN},
        headers=headers(payload["csrf_token"]),
    )
    assert response.status_code == 200
    return response.json(), client.cookies.get(SESSION)
