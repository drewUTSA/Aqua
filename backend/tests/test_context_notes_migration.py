"""Schema9→10 adds exactly one named table and preserves every old ledger row."""

from dataclasses import replace
from uuid import uuid4

import pytest

from storage.migrate import MigrationError, apply, migrations


def seed_nine(conn):
    assert apply(conn, migrations()[:9]) == 9
    conn.execute("SET ROLE aqua_app_owner")
    owner = conn.execute(
        "INSERT INTO app.users(display_name,profile_revision) VALUES('Unchanged nine',7) RETURNING id"
    ).fetchone()[0]
    ledger = conn.execute(
        "SELECT version,checksum,applied_at FROM app.schema_migrations ORDER BY version"
    ).fetchall()
    tables = conn.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname='app' ORDER BY tablename"
    ).fetchall()
    conn.execute("RESET ROLE")
    return owner, ledger, tables


def test_tenth_migration_is_additive_exact_and_least_privileged(app_database):
    owner, ledger, tables = seed_nine(app_database)
    assert apply(app_database) == apply(app_database) == 10
    app_database.execute("SET ROLE aqua_app_owner")
    assert (
        app_database.execute(
            "SELECT version,checksum,applied_at FROM app.schema_migrations WHERE version<=9 ORDER BY version"
        ).fetchall()
        == ledger
    )
    assert app_database.execute(
        "SELECT display_name,profile_revision FROM app.users WHERE id=%s", (owner,)
    ).fetchone() == ("Unchanged nine", 7)
    assert set(
        app_database.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='app' ORDER BY tablename"
        ).fetchall()
    ) == set(tables) | {("context_notes",)}
    assert app_database.execute(
        "SELECT has_table_privilege('aqua_app_runtime','app.context_notes','SELECT'),"
        "has_table_privilege('aqua_app_runtime','app.context_notes','INSERT'),"
        "has_table_privilege('aqua_app_runtime','app.context_notes','UPDATE'),"
        "has_table_privilege('aqua_app_runtime','app.context_notes','DELETE'),"
        "has_table_privilege('aqua_app_backup','app.context_notes','SELECT'),"
        "has_table_privilege('aqua_app_backup','app.context_notes','UPDATE'),"
        "has_table_privilege('aqua_app_runtime','app.schema_migrations','UPDATE')"
    ).fetchone() == (True, True, True, True, True, False, False)


def test_failed_tenth_migration_restores_old_catalog_and_ledger(app_database):
    owner, ledger, tables = seed_nine(app_database)
    broken = replace(migrations()[9], text=migrations()[9].text + "; SELECT 1/0;")
    with pytest.raises(MigrationError, match="rolled_back"):
        apply(app_database, (*migrations()[:9], broken))
    app_database.execute("SET ROLE aqua_app_owner")
    assert app_database.execute(
        "SELECT to_regclass('app.context_notes')"
    ).fetchone() == (None,)
    assert (
        app_database.execute(
            "SELECT version,checksum,applied_at FROM app.schema_migrations ORDER BY version"
        ).fetchall()
        == ledger
    )
    assert (
        app_database.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='app' ORDER BY tablename"
        ).fetchall()
        == tables
    )
    assert app_database.execute(
        "SELECT display_name FROM app.users WHERE id=%s", (owner,)
    ).fetchone() == ("Unchanged nine",)


def test_note_fk_and_tombstone_constraints_prevent_partial_scrubbing(storage):
    with storage.transaction() as conn:
        owner = conn.execute(
            "INSERT INTO app.users DEFAULT VALUES RETURNING id"
        ).fetchone()[0]
        item = conn.execute(
            "INSERT INTO app.context_notes(user_id,dataset_key,grant_version,kind,label,body,client_request_id,fingerprint,content_bytes)"
            "VALUES(%s,%s,1,'note','Label','Body',%s,%s,9) RETURNING id",
            (owner, "a" * 64, str(uuid4()), bytes(32)),
        ).fetchone()[0]
    from storage.pool import StorageUnavailable

    for statement, values in [
        ("DELETE FROM app.users WHERE id=%s", (owner,)),
        (
            "UPDATE app.context_notes SET deleted_at=clock_timestamp() WHERE id=%s",
            (item,),
        ),
        ("UPDATE app.context_notes SET content_bytes=0 WHERE id=%s", (item,)),
        ("UPDATE app.context_notes SET kind='system_instruction' WHERE id=%s", (item,)),
    ]:
        with pytest.raises(StorageUnavailable):
            with storage.transaction() as conn:
                conn.execute(statement, values)
