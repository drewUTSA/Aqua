"""Exercise logical recovery only inside the disposable synthetic PG container."""

import hashlib
from pathlib import Path
from collections.abc import Callable


def verify(docker: Callable, pg: str) -> dict:
    def sql(database: str, statement: bytes) -> bytes:
        return docker(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-A",
            "-t",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            database,
            data=statement,
        )

    sql(
        "aqua_app",
        b"""
SET ROLE aqua_app_runtime;
INSERT INTO app.users(id,status,display_name) VALUES ('00000000-0000-0000-0000-000000000001','active','Synthetic recovery');
INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at)
 VALUES ('00000000-0000-0000-0000-000000000001',decode(repeat('ab',32),'hex'),decode(repeat('cd',32),'hex'),0,'google',now()+interval '10 minutes',now()+interval '1 hour');
""",
    )
    dump = docker(
        "exec",
        "-e",
        "PGPASSWORD=fixture-only",
        pg,
        "pg_dump",
        "-h",
        "127.0.0.1",
        "-U",
        "aqua_app_backup",
        "-d",
        "aqua_app",
        "-Fc",
        "--no-owner",
    )
    # Earlier fixture tests may leave synthetic rows. Compare the full counts
    # rather than assuming their order left the database empty.
    count_sql = b"SELECT count(*) FROM app.users; SELECT count(*) FROM app.sessions; SELECT version FROM app.schema_migrations; SELECT has_table_privilege('aqua_app_runtime','app.users','INSERT'),has_table_privilege('aqua_app_runtime','app.schema_migrations','UPDATE');"
    expected = sql("aqua_app", count_sql).decode().splitlines()
    sql(
        "postgres",
        b"CREATE DATABASE aqua_restore OWNER aqua_app_owner TEMPLATE template0;",
    )
    docker(
        "exec",
        "-i",
        pg,
        "pg_restore",
        "--exit-on-error",
        "--no-owner",
        "--role=aqua_app_owner",
        "-U",
        "postgres",
        "-d",
        "aqua_restore",
        data=dump,
    )
    observed = (
        sql(
            "aqua_restore",
            count_sql,
        )
        .decode()
        .splitlines()
    )
    assert observed == expected and observed[2:] == ["1", "t|f"], observed
    denied = False
    try:
        sql("aqua_restore", b"SET ROLE aqua_app_backup; DELETE FROM app.users;")
    except RuntimeError:
        denied = True
    assert denied, "restored backup role gained write access"
    sql(
        "aqua_restore",
        (
            Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
        ).read_bytes(),
    )
    assert sql(
        "aqua_restore",
        b"SELECT count(*) FROM app.sessions WHERE revoked_at IS NULL; SELECT auth_epoch FROM app.users WHERE id='00000000-0000-0000-0000-000000000001';",
    ).decode().splitlines() == ["0", "1"]
    return {
        "status": "passed",
        "dump_bytes": len(dump),
        "dump_sha256": hashlib.sha256(dump).hexdigest(),
        "rows_and_privileges": "preserved",
        "restored_session_fence": "applied",
        "dump_storage": "memory_only",
    }
