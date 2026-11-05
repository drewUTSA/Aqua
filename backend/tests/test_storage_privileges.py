import psycopg
import pytest
from storage.pool import StorageUnavailable
from storage_fixtures import RUNTIME, BACKUP


def test_runtime_and_backup_have_no_owner_membership_or_ddl(storage):
    for dsn in (RUNTIME, BACKUP):
        with psycopg.connect(dsn, autocommit=True, connect_timeout=2) as conn:
            assert conn.execute(
                "SELECT pg_has_role(current_user,'aqua_app_owner','MEMBER')"
            ).fetchone() == (False,)
            for sql in (
                "CREATE TABLE app.forbidden(id int)",
                "CREATE ROLE forbidden_login",
                "SET ROLE aqua_app_owner",
                "CREATE SCHEMA forbidden",
                "TRUNCATE app.users",
                "UPDATE app.schema_migrations SET version=2",
            ):
                with pytest.raises(psycopg.Error):
                    conn.execute(sql)


def test_authentication_and_cross_database_access_are_denied(storage):
    for dsn in (
        RUNTIME.replace("fixture-only", "not-the-fixture-password"),
        "postgresql://nl2sql_reader@127.0.0.1:5432/aqua_app",
        RUNTIME.replace("aqua_app?", "aqua_test_bank?").replace("?sslmode=disable", ""),
    ):
        with pytest.raises(psycopg.Error):
            psycopg.connect(dsn, autocommit=True, connect_timeout=2)


def test_data_constraints_and_no_default_dataset_grant(storage):
    with storage.transaction() as conn:
        user = conn.execute(
            "INSERT INTO app.users(display_name) VALUES ('Synthetic A') RETURNING id"
        ).fetchone()[0]
        assert conn.execute(
            "SELECT count(*) FROM app.dataset_grants WHERE user_id=%s", (user,)
        ).fetchone() == (0,)
    for statement, params in [
        ("INSERT INTO app.users(status) VALUES ('admin')", ()),
        ("INSERT INTO app.user_preferences(user_id,values) VALUES (%s,'[]')", (user,)),
        (
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) VALUES (%s,'x','y',0,'google',now()+interval '1 minute',now()+interval '1 hour')",
            (user,),
        ),
    ]:
        with pytest.raises(StorageUnavailable):
            with storage.transaction() as conn:
                conn.execute(statement, params)
    assert storage.readiness()["schema_version"] == 8


def test_session_child_cannot_reference_another_owner(storage):
    with storage.transaction() as conn:
        a, b = [
            conn.execute(
                "INSERT INTO app.users DEFAULT VALUES RETURNING id"
            ).fetchone()[0]
            for _ in range(2)
        ]
        session = conn.execute(
            "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) VALUES (%s,%s,%s,0,'google',now()+interval '1 minute',now()+interval '1 hour') RETURNING id",
            (a, b"a" * 32, b"b" * 32),
        ).fetchone()[0]
    with pytest.raises(StorageUnavailable):
        with storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.auth_challenges(user_id,session_id,purpose,secret_digest,expires_at) VALUES (%s,%s,'reauth',%s,now()+interval '1 minute')",
                (b, session, b"c" * 32),
            )
