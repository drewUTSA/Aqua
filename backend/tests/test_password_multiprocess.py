"""Independent processes must share the two-slot password-memory boundary."""

from multiprocessing import get_context
from queue import Empty
import time

import pytest


def _hash_worker(start, release, reports) -> None:
    # Spawn starts a fresh interpreter: install the fixture boundary before any
    # application import. No developer DSN, dotenv, provider or network is used.
    from safety import install

    install()
    from auth.config import AuthLimited
    from auth.password_hash import PasswordHasher
    from auth.password_limits import hash_slot
    from auth.password_policy import PasswordPolicy
    from storage.config import StorageSettings
    from storage.pool import Storage

    dsn = "postgresql://aqua_app_runtime:fixture-only@127.0.0.1:5432/aqua_app?sslmode=disable"
    service = Storage(StorageSettings(True, dsn, 1, 1, 0.4))
    try:
        with service.transaction() as conn:
            assert conn.execute("SELECT 1").fetchone() == (1,)
        reports.put("ready")
        if not start.wait(5):
            reports.put("failed")
            return
        try:
            with hash_slot(service, PasswordPolicy()):
                # This process has exactly one pooled connection. Its successful
                # use inside the slot proves the lease was released before hash.
                with service.transaction() as conn:
                    assert conn.execute("SELECT 1").fetchone() == (1,)
                hasher = PasswordHasher()
                encoded = hasher.hash("synthetic multiprocess fixture password 87!")
                assert hasher.verify(
                    "synthetic multiprocess fixture password 87!", encoded
                )
                reports.put("admitted_hash_and_free_connection")
                if not release.wait(5):
                    reports.put("failed")
        except AuthLimited:
            reports.put("denied")
    except Exception:
        # Do not return raw child exceptions/DSNs, even on a failed fixture.
        reports.put("failed")
    finally:
        service.close()


def _receive(reports, count: int) -> list[str]:
    deadline = time.monotonic() + 5
    values = []
    for _ in range(count):
        try:
            values.append(reports.get(timeout=max(0.001, deadline - time.monotonic())))
        except Empty:
            pytest.fail("isolated password-worker coordination timed out")
    return values


def test_database_hash_cap_covers_three_real_processes_and_recovers(storage):
    """Each child has its own two-slot semaphore; only PostgreSQL can deny #3."""
    from auth.password_limits import hash_slot
    from auth.password_policy import PasswordPolicy

    context = get_context("spawn")
    start, release = context.Event(), context.Event()
    reports = context.Queue(maxsize=12)
    workers = [
        context.Process(target=_hash_worker, args=(start, release, reports))
        for _ in range(3)
    ]
    try:
        for worker in workers:
            worker.start()
        assert _receive(reports, 3) == ["ready"] * 3
        start.set()
        assert sorted(_receive(reports, 3)) == [
            "admitted_hash_and_free_connection",
            "admitted_hash_and_free_connection",
            "denied",
        ]
        with storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.password_hash_slots"
            ).fetchone() == (2,)
        release.set()
        for worker in workers:
            worker.join(timeout=5)
            assert not worker.is_alive() and worker.exitcode == 0
        with storage.transaction() as conn:
            assert conn.execute(
                "SELECT count(*) FROM app.password_hash_slots"
            ).fetchone() == (0,)
        with hash_slot(storage, PasswordPolicy()):
            with storage.transaction() as conn:
                assert conn.execute(
                    "SELECT count(*) FROM app.password_hash_slots"
                ).fetchone() == (1,)
    finally:
        start.set()
        release.set()
        for worker in workers:
            if worker.pid is not None:
                worker.join(timeout=1)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(timeout=2)
        reports.close()
        reports.join_thread()
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
