"""Provide isolated browser identity fixtures only to tests in this directory."""

import pytest
from dataclasses import replace
from fastapi.testclient import TestClient

import main
from auth import router
from nl2sql.config import Settings
from storage.pool import Storage
from legacy_contract_fixture import install
from _auth_test_helpers import CLIENT_ID, EMAIL, ORIGIN, SUBJECT
from _durable_route_helpers import durable_browser  # noqa: F401
from _password_route_helpers import password_browser  # noqa: F401


@pytest.fixture
def browser(monkeypatch: pytest.MonkeyPatch, storage):
    # One connection still proves external work releases its DB lease. Two
    # lifecycle readers and the HTTP request need bounded queue space, rather
    # than turning identity tests into the separate pool-saturation tests.
    storage = Storage(replace(storage.settings, max_waiting=4, wait_seconds=2))
    settings = Settings(
        database_url=main.SETTINGS.database_url,
        google_client_id=CLIENT_ID,
        session_secret="test-session-secret-" * 4,
        app_origin=ORIGIN,
        auth_allowed_emails=frozenset({EMAIL}),
    )
    monkeypatch.setattr(main.app.state, "settings", settings)
    monkeypatch.setattr(main.app.state, "storage", storage)
    # These cases retain the real identity/CSRF/grant dependencies and patch
    # only the query service's schema/provider seams. Actual child/admission
    # behavior is covered by the independent P07 legacy integration tests.
    install(monkeypatch)
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
