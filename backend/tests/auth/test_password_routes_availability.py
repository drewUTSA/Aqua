"""Prove denial precedes costly work and ordinary accounts recover safely."""

from contextlib import contextmanager
from dataclasses import replace
from statistics import median
import time

from fastapi.testclient import TestClient
import pytest

import main
from auth import router
from auth.mailconfig import MailPolicy
from storage.pool import StorageUnavailable
from _auth_test_helpers import ORIGIN
from _password_route_helpers import COOKIE, EMAIL, PASSWORD, ROOT, SESSION


def test_password_login_is_independent_of_google_and_mail_availability(
    password_browser, monkeypatch
):
    browser = password_browser
    browser.register()
    calls = []

    def provider(*args, **kwargs):
        calls.append(True)
        raise AssertionError("password login attempted Google verification")

    monkeypatch.setattr(router, "verify_google_token", provider)
    browser.store.mail_policy = MailPolicy()
    accepted = browser.login()
    assert accepted.status_code == 200 and calls == []
    assert accepted.json()["user"]["email"] == EMAIL
    assert browser.client.get("/api/auth/me").status_code == 200
    request = browser.post(
        "reset-request", "/password-reset-requests", {"email": EMAIL}
    )
    assert request.status_code == 503
    assert browser.client.get("/api/auth/me").status_code == 200


def test_consumed_bootstrap_is_not_reusable_even_with_copied_cookie(password_browser):
    browser = password_browser
    pending, cookie = browser.bootstrap("login")
    headers = {
        "Origin": ORIGIN,
        "X-CSRF-Token": pending["csrf_token"],
        "Cookie": f"{COOKIE}={cookie}",
    }
    one = browser.client.post(
        ROOT + "/password-login",
        json={"email": EMAIL, "password": PASSWORD},
        headers=headers,
    )
    assert one.status_code == 401 and browser.hash_calls == ["verify"]
    two = TestClient(main.app, base_url=ORIGIN).post(
        ROOT + "/password-login",
        json={"email": EMAIL, "password": PASSWORD},
        headers=headers,
    )
    assert two.status_code == 403 and browser.hash_calls == ["verify"]


def test_wrong_and_absent_accounts_have_same_public_failure_and_hash_work(
    password_browser,
):
    browser = password_browser
    browser.register()
    before = len(browser.hash_calls)
    existing = browser.login(password="Incorrect synthetic account password 4!")
    absent = browser.login(email="unknown.reader@example.test")
    assert existing.status_code == absent.status_code == 401
    assert existing.content == absent.content
    assert browser.hash_calls[before:] == ["verify", "verify"]
    assert browser.client.cookies.get(SESSION) is None
    with browser.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)


def test_address_limit_survives_cookie_and_header_churn_then_recovers(password_browser):
    browser = password_browser
    browser.register()
    browser.store.password_policy = replace(
        browser.store.password_policy, login_address_limit=1
    )
    before = len(browser.hash_calls)
    assert (
        browser.login(password="Incorrect synthetic account password 4!").status_code
        == 401
    )
    browser.client.cookies.clear()
    pending, _ = browser.bootstrap("login")
    limited = browser.client.post(
        ROOT + "/password-login",
        json={"email": EMAIL.upper(), "password": PASSWORD},
        headers={
            "Origin": ORIGIN,
            "X-CSRF-Token": pending["csrf_token"],
            "CF-Connecting-IP": "198.51.100.22",
            "X-Forwarded-For": "203.0.113.43",
            "Forwarded": "for=192.0.2.64",
        },
    )
    assert limited.status_code == 429
    assert 1 <= int(limited.headers["retry-after"]) <= 60
    assert browser.hash_calls[before:] == ["verify"]
    with browser.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.sessions").fetchone() == (0,)
        conn.execute(
            "UPDATE app.password_admission SET expires_at=clock_timestamp()-interval '1 second'"
        )
    assert browser.login().status_code == 200
    assert browser.hash_calls[before:] == ["verify", "verify"]


def test_mail_limit_stops_queue_growth_without_hash_work_then_recovers(
    password_browser,
):
    browser = password_browser
    browser.store.password_policy = replace(
        browser.store.password_policy, mail_peer_limit=1
    )
    first = browser.post("registration", "/registrations", {"email": EMAIL})
    denied = browser.post(
        "registration", "/registrations", {"email": "different.reader@example.test"}
    )
    assert first.status_code == 202 and denied.status_code == 429
    assert browser.hash_calls == []
    with browser.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (1,)
        conn.execute(
            "UPDATE app.password_admission SET expires_at=clock_timestamp()-interval '1 second'"
        )
    assert (
        browser.post(
            "registration", "/registrations", {"email": "different.reader@example.test"}
        ).status_code
        == 202
    )


@pytest.mark.parametrize(
    "action,path,payload",
    [
        ("registration", "/registrations", {"email": EMAIL}),
        ("login", "/password-login", {"email": EMAIL, "password": PASSWORD}),
        (
            "verification",
            "/email-verifications",
            {"token": "A" * 43, "password": PASSWORD},
        ),
        ("reset-request", "/password-reset-requests", {"email": EMAIL}),
        ("reset", "/password-resets", {"token": "A" * 43, "password": PASSWORD}),
    ],
)
def test_storage_outage_never_hashes_or_leaks_driver_details(
    password_browser, monkeypatch, action, path, payload, caplog
):
    browser = password_browser
    pending, _ = browser.bootstrap(action)

    @contextmanager
    def unavailable():
        raise StorageUnavailable("PRIVATE_PASSWORD_DATABASE_CANARY")
        yield

    monkeypatch.setattr(browser.storage, "transaction", unavailable)
    response = browser.client.post(
        ROOT + path,
        json=payload,
        headers={"Origin": ORIGIN, "X-CSRF-Token": pending["csrf_token"]},
    )
    assert response.status_code == 503 and browser.hash_calls == []
    assert "PRIVATE_PASSWORD_DATABASE_CANARY" not in response.text + caplog.text
    assert PASSWORD not in response.text + caplog.text


def test_known_and_unknown_email_requests_share_bounded_timing_floor(password_browser):
    browser = password_browser
    browser.register()
    observed = {"known": [], "unknown": []}
    # All six requests retain real DB admission/queries and encrypted enqueue;
    # this is a small timing regression, not a constant-time security claim.
    for index in range(3):
        for kind, address in (
            ("known", EMAIL),
            ("unknown", f"timing.reader.{index}@example.test"),
        ):
            pending, _ = browser.bootstrap("registration")
            started = time.monotonic()
            response = browser.client.post(
                ROOT + "/registrations",
                json={"email": address},
                headers={"Origin": ORIGIN, "X-CSRF-Token": pending["csrf_token"]},
            )
            observed[kind].append(time.monotonic() - started)
            assert response.status_code == 202
    assert all(elapsed >= 0.045 for samples in observed.values() for elapsed in samples)
    assert abs(median(observed["known"]) - median(observed["unknown"])) < 0.05


def test_pausing_new_mail_flows_preserves_existing_password_login(
    password_browser, monkeypatch
):
    browser = password_browser
    browser.register()
    monkeypatch.setenv("PASSWORD_REGISTRATION_ENABLED", "false")
    monkeypatch.setenv("PASSWORD_RECOVERY_ENABLED", "false")
    assert (
        browser.client.get(
            ROOT + "/bootstrap", params={"action": "registration"}
        ).status_code
        == 503
    )
    assert (
        browser.client.get(
            ROOT + "/bootstrap", params={"action": "reset-request"}
        ).status_code
        == 503
    )
    assert browser.login().status_code == 200
