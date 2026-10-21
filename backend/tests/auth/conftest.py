"""Provide isolated browser identity fixtures only to tests in this directory."""

import pytest
from fastapi.testclient import TestClient

import main
from auth import router
from nl2sql.config import Settings
from _auth_test_helpers import CLIENT_ID, EMAIL, ORIGIN, SUBJECT
from _durable_route_helpers import durable_browser  # noqa: F401
from _password_route_helpers import password_browser  # noqa: F401


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch, storage):
    settings = Settings(
        database_url=main.SETTINGS.database_url,
        google_client_id=CLIENT_ID,
        session_secret="test-session-secret-" * 4,
        app_origin=ORIGIN,
        auth_allowed_emails=frozenset({EMAIL}),
    )
    monkeypatch.setattr(main.app.state, "settings", settings)
    monkeypatch.setattr(main.app.state, "storage", storage)
    claims = {
        "sub": SUBJECT,
        "email": EMAIL,
        "email_verified": True,
        "name": "Aqua Reader",
        "picture": "https://lh3.googleusercontent.com/avatar.png",
    }
    verified = []

    def verify(credential, client_id):
        verified.append((credential, client_id))
        return claims.copy()

    monkeypatch.setattr(router, "verify_google_token", verify)
    with TestClient(main.app, base_url=ORIGIN) as client:
        yield client, claims, verified
