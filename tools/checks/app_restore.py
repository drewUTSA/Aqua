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
    # Seed schema-3 work independently of whichever fixture ran last. A
    # restored instance must not inherit abandoned hash slots or replay mail.
    sql(
        "aqua_app",
        b"SET ROLE aqua_app_owner; INSERT INTO app.password_hash_slots(id) VALUES ('a78c4e72-c149-4f85-80f1-422cd0637eaa'); INSERT INTO app.account_mail(id,purpose,recipient_digest,ciphertext,expires_at) VALUES ('f4d6b61d-11be-4510-bca3-0521dd724aaa','password_changed',decode(repeat('00',32),'hex'),decode(repeat('ab',30),'hex'),now()+interval '1 hour'); UPDATE app.account_mail_control SET lease_id='5da38ab6-643a-4152-93b5-894c4f8a8651',lease_expires_at=now()+interval '1 minute' WHERE singleton;",
    )
    # Recovery must preserve spent anti-spam history rather than creating a new
    # sending allowance when restored pending proofs/jobs are invalidated.
    sql(
        "aqua_app",
        b"SET ROLE aqua_app_runtime; INSERT INTO app.mail_recipient_budget(purpose,recipient_digest,issued_at,last_queued_at,expires_at) VALUES ('verify_email',decode(repeat('ef',32),'hex'),ARRAY[now()-interval '18 minutes',now()-interval '12 minutes',now()-interval '6 minutes'],now()-interval '6 minutes',now()+interval '24 hours') ON CONFLICT(purpose,recipient_digest) DO UPDATE SET issued_at=EXCLUDED.issued_at,last_queued_at=EXCLUDED.last_queued_at,expires_at=EXCLUDED.expires_at;",
    )
    recipient_sql = b"SELECT issued_at,last_queued_at,expires_at FROM app.mail_recipient_budget WHERE purpose='verify_email' AND recipient_digest=decode(repeat('ef',32),'hex'); SELECT has_table_privilege('aqua_app_runtime','app.mail_recipient_budget','UPDATE'),has_table_privilege('aqua_app_backup','app.mail_recipient_budget','UPDATE');"
    recipient_expected = sql("aqua_app", recipient_sql)
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
    count_sql = b"SELECT count(*) FROM app.users; SELECT count(*) FROM app.sessions; SELECT version FROM app.schema_migrations ORDER BY version; SELECT has_table_privilege('aqua_app_runtime','app.users','INSERT'),has_table_privilege('aqua_app_runtime','app.schema_migrations','UPDATE');"
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
    assert observed == expected and observed[2:] == ["1", "2", "3", "t|f"], observed
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
    assert sql(
        "aqua_restore",
        b"SELECT count(*) FROM app.password_hash_slots; SELECT count(*) FROM app.account_mail WHERE state IN ('pending','sending'); SELECT state,ciphertext=decode(repeat('00',30),'hex') FROM app.account_mail WHERE id='f4d6b61d-11be-4510-bca3-0521dd724aaa'; SELECT lease_id IS NULL AND lease_expires_at IS NULL FROM app.account_mail_control WHERE singleton;",
    ).decode().splitlines() == ["0", "0", "expired|t", "t"]
    assert sql("aqua_restore", recipient_sql) == recipient_expected
    assert recipient_expected.decode().splitlines()[-1] == "t|f"
    return {
        "status": "passed",
        "dump_bytes": len(dump),
        "dump_sha256": hashlib.sha256(dump).hexdigest(),
        "rows_and_privileges": "preserved",
        "restored_session_fence": "applied",
        "restored_hash_and_mail_fence": "applied",
        "restored_recipient_budget": "preserved_with_runtime_backup_privileges",
        "dump_storage": "memory_only",
    }
