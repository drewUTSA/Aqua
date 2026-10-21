from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import time
import psycopg
import pytest
from fastapi.testclient import TestClient
import main
from storage.migrate import apply
from storage.pool import Storage, StorageUnavailable
from storage_fixtures import RUNTIME, SETTINGS, CANARY


def test_storage_authentication_outage_fails_closed_and_redacts(caplog, app_database):
    apply(app_database)
    service = Storage(
        replace(
            SETTINGS, dsn=RUNTIME.replace("fixture-only", "not-the-fixture-password")
        )
    )
    try:
        with pytest.raises(StorageUnavailable):
            service.readiness()
    finally:
        service.close()
    assert "not-the-fixture-password" not in caplog.text


def test_pooled_identity_state_and_failed_transactions_do_not_leak(storage, caplog):
    with pytest.raises(StorageUnavailable):
        with storage.transaction() as conn:
            conn.execute("SELECT set_config('app.user_id',%s,false)", (CANARY,))
            conn.execute("SELECT 1/0")
    with storage.transaction() as conn:
        assert conn.execute("SELECT current_setting('app.user_id',true)").fetchone()[
            0
        ] in (None, "")
        assert conn.execute("SELECT 1").fetchone() == (1,)
    assert CANARY not in caplog.text
    assert "action=deny" in caplog.text


def test_successful_lease_also_discards_session_scope(storage):
    with storage.transaction() as conn:
        conn.execute("SELECT set_config('app.user_id',%s,false)", (CANARY,))
    with storage.transaction() as conn:
        assert conn.execute("SELECT current_setting('app.user_id',true)").fetchone()[
            0
        ] in (None, "")


def test_pool_replaces_a_disconnected_database_connection(storage):
    with storage.transaction() as conn:
        pid = conn.info.backend_pid
    # A role may terminate its own backend; no fixture superuser is needed.
    with psycopg.connect(RUNTIME, autocommit=True, connect_timeout=2) as killer:
        assert killer.execute("SELECT pg_terminate_backend(%s)", (pid,)).fetchone() == (
            True,
        )
    assert storage.readiness()["status"] == "ready"


def test_readiness_rejects_a_newer_schema_version(app_database):
    apply(app_database)
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute("UPDATE app.schema_migrations SET version=4 WHERE version=3")
    app_database.execute("RESET ROLE")
    service = Storage(SETTINGS)
    try:
        with pytest.raises(StorageUnavailable, match="schema_unavailable"):
            service.readiness()
    finally:
        service.close()


def test_pool_queue_is_bounded_and_recovers(storage):
    entered = threading.Event()
    release = threading.Event()

    def hold():
        with storage.transaction():
            entered.set()
            assert release.wait(3)

    def ordinary():
        with storage.transaction() as conn:
            return conn.execute("SELECT 1").fetchone()

    with ThreadPoolExecutor(max_workers=3) as pool:
        holder = pool.submit(hold)
        assert entered.wait(2)
        waiter = pool.submit(ordinary)
        deadline = time.monotonic() + 1
        while (
            storage._pool.get_stats().get("requests_waiting", 0) < 1
            and time.monotonic() < deadline
        ):
            time.sleep(0.005)
        try:
            with pytest.raises(StorageUnavailable):
                ordinary()
        finally:
            release.set()
        holder.result()
        assert waiter.result() == (1,)
    assert storage.readiness()["status"] == "ready"


def test_readiness_does_not_replace_liveness_or_leak_errors(monkeypatch):
    class FailedStorage:
        def readiness(self):
            raise StorageUnavailable(CANARY)

    monkeypatch.setattr(main.app.state, "storage", FailedStorage())
    client = TestClient(main.app)
    assert client.get("/api/health").status_code == 200
    response = client.get("/api/ready")
    assert response.status_code == 503 and CANARY not in response.text
    assert response.headers["Cache-Control"] == "no-store"
