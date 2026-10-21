"""Cost admission must protect hashes while leaving revocation available."""

from concurrent.futures import ThreadPoolExecutor
import threading

from fastapi.testclient import TestClient

import main
from _auth_test_helpers import ORIGIN
from _password_route_helpers import COOKIE, EMAIL, PASSWORD, ROOT


def test_hash_flood_has_two_slots_no_db_leases_and_logout_stays_available(
    password_browser, monkeypatch
):
    browser = password_browser
    browser.register()
    logged_in = browser.login()
    assert logged_in.status_code == 200
    requests = [browser.bootstrap("login") for _ in range(3)]
    entered = threading.Barrier(3)
    release = threading.Event()
    original = browser.store.hasher.verify
    active = []
    lock = threading.Lock()

    def paused_hash(*args, **kwargs):
        # This read requires the fixture's sole pooled connection. A password
        # verifier retaining a DB lease would deadlock before reaching the gate.
        with browser.storage.transaction() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
        with lock:
            active.append(True)
        entered.wait(timeout=5)
        assert release.wait(timeout=5)
        return original(*args, **kwargs)

    monkeypatch.setattr(browser.store.hasher, "verify", paused_hash)
    browser.storage.readiness()

    def submit(index):
        pending, cookie = requests[index]
        return TestClient(main.app, base_url=ORIGIN).post(
            ROOT + "/password-login",
            json={"email": EMAIL, "password": PASSWORD},
            headers={
                "Origin": ORIGIN,
                "X-CSRF-Token": pending["csrf_token"],
                "Cookie": f"{COOKIE}={cookie}",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(submit, index) for index in range(2)]
        try:
            entered.wait(timeout=5)
            with browser.storage.transaction() as conn:
                assert conn.execute(
                    "SELECT count(*) FROM app.password_hash_slots"
                ).fetchone() == (2,)
            rejected = submit(2)
            assert rejected.status_code == 429 and len(active) == 2
            assert browser.client.get("/api/health").status_code == 200
            revoked = browser.client.post(
                "/api/auth/logout",
                headers={
                    "Origin": ORIGIN,
                    "X-CSRF-Token": logged_in.json()["csrf_token"],
                },
            )
            assert revoked.status_code == 204
        finally:
            release.set()
        assert [future.result(timeout=5).status_code for future in futures] == [
            200,
            200,
        ]
    with browser.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
    monkeypatch.setattr(browser.store.hasher, "verify", original)
    assert browser.login().status_code == 200
