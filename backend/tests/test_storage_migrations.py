from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import threading
import time
import psycopg
import pytest
from storage.migrate import Migration, MigrationError, apply, migrations
from storage_fixtures import MIGRATOR


def test_migration_repeats_without_duplicate_state(app_database):
    assert apply(app_database) == apply(app_database) == 3
    app_database.execute("SET ROLE aqua_app_owner")
    assert app_database.execute(
        "SELECT count(*) FROM app.schema_migrations"
    ).fetchone() == (3,)


def test_failed_migration_rolls_back_schema_and_ledger(app_database):
    broken = Migration(1, "CREATE TABLE app.partial_fixture(id int); SELECT 1/0")
    with pytest.raises(MigrationError, match="rolled_back"):
        apply(app_database, (broken,))
    app_database.execute("SET ROLE aqua_app_owner")
    assert app_database.execute(
        "SELECT to_regclass('app.partial_fixture'),to_regclass('app.schema_migrations')"
    ).fetchone() == (None, None)
    app_database.execute("RESET ROLE")
    assert apply(app_database) == 3


def test_unknown_or_tampered_migration_is_not_silently_accepted(app_database):
    apply(app_database)
    with pytest.raises(MigrationError, match="history_mismatch"):
        apply(
            app_database,
            (
                replace(migrations()[0], text="SELECT 1"),
                *migrations()[1:],
            ),
        )


def test_concurrent_migrators_apply_one_version(app_database):
    # The two-slot role cap is intentional; don't occupy a third fixture slot.
    app_database.close()

    def migrate():
        with psycopg.connect(MIGRATOR, autocommit=True, connect_timeout=2) as conn:
            return apply(conn)

    with ThreadPoolExecutor(max_workers=2) as workers:
        assert list(workers.map(lambda _: migrate(), range(2))) == [3, 3]


def test_disconnect_during_migration_leaves_no_partial_schema(app_database):
    started = threading.Event()
    pid = []

    def interrupted():
        with psycopg.connect(MIGRATOR, autocommit=True, connect_timeout=2) as conn:
            pid.append(conn.info.backend_pid)
            started.set()
            with pytest.raises(MigrationError, match="rolled_back"):
                apply(
                    conn,
                    (
                        Migration(
                            1,
                            "CREATE TABLE app.interrupted_fixture(id int); SELECT pg_sleep(5)",
                        ),
                    ),
                )

    with ThreadPoolExecutor(max_workers=1) as worker:
        result = worker.submit(interrupted)
        assert started.wait(2)
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            row = app_database.execute(
                "SELECT wait_event FROM pg_stat_activity WHERE pid=%s", (pid[0],)
            ).fetchone()
            if row == ("PgSleep",):
                break
            time.sleep(0.005)
        else:
            pytest.fail("migration never reached the interruptible transaction")
        assert app_database.execute(
            "SELECT pg_terminate_backend(%s)", (pid[0],)
        ).fetchone() == (True,)
        result.result(timeout=3)
    app_database.execute("SET ROLE aqua_app_owner")
    assert app_database.execute(
        "SELECT to_regclass('app.interrupted_fixture'),to_regclass('app.schema_migrations')"
    ).fetchone() == (None, None)


def test_runtime_cannot_invoke_migrations(storage):
    with pytest.raises(MigrationError, match="identity_invalid"):
        with storage.transaction() as conn:
            apply(conn)
