"""Actual schema-7 upgrade, rollback, immutable ledger and least privilege."""

from dataclasses import replace
import hashlib
from uuid import uuid4

import pytest

from privacy import policy
from storage.migrate import MigrationError, apply, migrations
from storage.pool import StorageUnavailable


def seven(conn):
    assert apply(conn, migrations()[:7]) == 7
    conn.execute("SET ROLE aqua_app_owner")
    owner, session, challenge = uuid4(), uuid4(), uuid4()
    conn.execute(
        "INSERT INTO app.users(id,status,display_name,profile_revision,email_revision) VALUES(%s,'active','Unchanged seven',9,4)",
        (owner,),
    )
    conn.execute(
        "INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version) VALUES(%s,'synthetic-migration-password-hash',1)",
        (owner,),
    )
    conn.execute(
        "INSERT INTO app.sessions(id,user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) VALUES(%s,%s,%s,%s,0,'password',now()+interval '10 minutes',now()+interval '1 hour')",
        (session, owner, b"s" * 32, b"c" * 32),
    )
    target = hashlib.sha256(
        b'["aqua-account-action-v1","sessions_revoke_all",null]'
    ).digest()
    conn.execute(
        "INSERT INTO app.auth_challenges(id,user_id,session_id,purpose,secret_digest,binding_digest,account_operation,account_target_digest,account_auth_epoch,expires_at,consumed_at) VALUES(%s,%s,%s,'reauth',%s,%s,'sessions_revoke_all',%s,0,now()+interval '300 seconds',now())",
        (challenge, owner, session, b"h" * 32, b"b" * 32, target),
    )
    conn.execute(
        "INSERT INTO app.account_action_proofs(user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,password_changed_at,expires_at) SELECT user_id,%s,%s,%s,0,'sessions_revoke_all',%s,'password',changed_at,now()+interval '240 seconds' FROM app.password_credentials WHERE user_id=%s",
        (session, challenge, b"p" * 32, target, owner),
    )
    ledger = conn.execute(
        "SELECT version,checksum,applied_at FROM app.schema_migrations ORDER BY version"
    ).fetchall()
    proof = conn.execute(
        "SELECT * FROM app.account_action_proofs WHERE user_id=%s", (owner,)
    ).fetchone()
    conn.execute("RESET ROLE")
    return owner, ledger, proof


def test_eighth_migration_is_additive_and_preserves_existing_proof_and_ledger(
    app_database,
):
    owner, ledger, proof = seven(app_database)
    assert apply(app_database) == apply(app_database) == 8
    app_database.execute("SET ROLE aqua_app_owner")
    assert (
        app_database.execute(
            "SELECT version,checksum,applied_at FROM app.schema_migrations WHERE version<=7 ORDER BY version"
        ).fetchall()
        == ledger
    )
    assert app_database.execute(
        "SELECT display_name,profile_revision,email_revision,auth_epoch,privacy_epoch FROM app.users WHERE id=%s",
        (owner,),
    ).fetchone() == ("Unchanged seven", 9, 4, 0, 1)
    assert (
        app_database.execute(
            "SELECT * FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone()
        == proof
    )
    assert app_database.execute(
        "SELECT reserved_bytes,stored_bytes,worker_owner,worker_until,worker_job FROM app.privacy_control WHERE singleton"
    ).fetchone() == (0, 0, None, None, None)


def test_failed_eighth_migration_rolls_back_every_new_table_and_epoch(app_database):
    owner, ledger, proof = seven(app_database)
    broken = replace(migrations()[7], text=migrations()[7].text + "; SELECT 1/0;")
    with pytest.raises(MigrationError, match="rolled_back"):
        apply(app_database, (*migrations()[:7], broken))
    app_database.execute("SET ROLE aqua_app_owner")
    assert (
        app_database.execute(
            "SELECT version,checksum,applied_at FROM app.schema_migrations ORDER BY version"
        ).fetchall()
        == ledger
    )
    assert (
        app_database.execute(
            "SELECT * FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone()
        == proof
    )
    assert app_database.execute(
        "SELECT to_regclass('app.data_exports'),to_regclass('app.data_export_chunks'),to_regclass('app.privacy_control'),to_regclass('app.privacy_admission')"
    ).fetchone() == (None, None, None, None)
    assert app_database.execute(
        "SELECT count(*) FROM information_schema.columns WHERE table_schema='app' AND table_name='users' AND column_name='privacy_epoch'"
    ).fetchone() == (0,)
    app_database.execute("RESET ROLE")
    assert apply(app_database) == 8


def test_private_chunks_require_exact_owner_digest_size_and_single_live_owner(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client()
    _, foreign = fixture.client("B")
    job, _ = fixture.queue(client)
    for selected_owner, body, digest in [
        (foreign, b"x", hashlib.sha256(b"x").digest()),
        (owner, b"x", b"z" * 32),
        (
            owner,
            b"x" * (policy.CHUNK_BYTES + 1),
            hashlib.sha256(b"x" * (policy.CHUNK_BYTES + 1)).digest(),
        ),
    ]:
        with pytest.raises(StorageUnavailable):
            with fixture.world.storage.transaction() as conn:
                conn.execute(
                    "INSERT INTO app.data_export_chunks(user_id,job_id,generation,ordinal,body,digest) VALUES(%s,%s,1,0,%s,%s)",
                    (selected_owner, job["id"], body, digest),
                )
    with fixture.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.data_export_chunks"
        ).fetchone() == (0,)
    with pytest.raises(StorageUnavailable):
        with fixture.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.data_exports SET expires_at=expires_at+interval '1 second' WHERE id=%s",
                (job["id"],),
            )


def test_runtime_and_backup_private_output_privileges_remain_separate(
    storage, app_database
):
    app_database.execute("SET ROLE aqua_app_owner")
    for table in (
        "data_exports",
        "data_export_chunks",
        "privacy_control",
        "privacy_admission",
    ):
        assert app_database.execute(
            "SELECT has_table_privilege('aqua_app_backup',%s,'SELECT'),has_table_privilege('aqua_app_backup',%s,'UPDATE'),has_table_privilege('aqua_app_runtime',%s,'TRUNCATE')",
            ("app." + table,) * 3,
        ).fetchone() == (True, False, False)
    with pytest.raises(StorageUnavailable):
        with storage.transaction() as conn:
            conn.execute("ALTER TABLE app.data_exports ADD COLUMN must_fail integer")
    with pytest.raises(StorageUnavailable):
        with storage.transaction() as conn:
            conn.execute("DELETE FROM app.privacy_control WHERE singleton")
    assert storage.readiness()["schema_version"] == 8
