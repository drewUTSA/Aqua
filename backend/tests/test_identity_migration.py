"""Actual additive schema-6 upgrade, legacy-proof invalidation and role fences."""

from dataclasses import replace
import hashlib
import psycopg
import pytest
from auth.admission import cleanup
from auth.config import AuthPolicy
from storage.migrate import MigrationError, apply, migrations
from storage.pool import StorageUnavailable
from security_action_fixtures import PATH


def legacy_six(app_database):
    assert apply(app_database, migrations()[:6]) == 6
    app_database.execute("SET ROLE aqua_app_owner")
    owner = app_database.execute(
        "INSERT INTO app.users(status,display_name,profile_revision) VALUES('active','Before identity actions',8) RETURNING id"
    ).fetchone()[0]
    app_database.execute(
        "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) VALUES(%s,'legacy@example.invalid','legacy@example.invalid',now(),'google',true)",
        (owner,),
    )
    identity = app_database.execute(
        "INSERT INTO app.external_identities(user_id,provider,issuer,subject,revision) VALUES(%s,'google','https://accounts.google.com','legacy-provider-subject',9) RETURNING id",
        (owner,),
    ).fetchone()[0]
    session = app_database.execute(
        "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) VALUES(%s,%s,%s,0,'google',now()+interval '10 minutes',now()+interval '1 hour') RETURNING id",
        (owner, b"s" * 32, b"c" * 32),
    ).fetchone()[0]
    target = hashlib.sha256(
        b'["aqua-account-action-v1","sessions_revoke_all",null]'
    ).digest()
    challenge = app_database.execute(
        "INSERT INTO app.auth_challenges(user_id,session_id,purpose,secret_digest,binding_digest,account_operation,account_target_digest,account_auth_epoch,expires_at,consumed_at) VALUES(%s,%s,'reauth',%s,%s,'sessions_revoke_all',%s,0,now()+interval '300 seconds',now()) RETURNING id",
        (owner, session, b"h" * 32, b"b" * 32, target),
    ).fetchone()[0]
    proof = app_database.execute(
        "INSERT INTO app.account_action_proofs(user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,external_identity_id,expires_at) VALUES(%s,%s,%s,%s,0,'sessions_revoke_all',%s,'google',%s,now()+interval '240 seconds') RETURNING id",
        (owner, session, challenge, b"p" * 32, target, identity),
    ).fetchone()[0]
    old = app_database.execute(
        "SELECT version,checksum FROM app.schema_migrations ORDER BY version"
    ).fetchall()
    app_database.execute("RESET ROLE")
    return owner, identity, proof, old


def test_upgrade_invalidates_legacy_google_proof_without_inventing_snapshot(
    app_database,
):
    owner, identity, proof, old = legacy_six(app_database)
    assert (
        apply(app_database, migrations()[:7])
        == apply(app_database, migrations()[:7])
        == 7
    )
    app_database.execute("SET ROLE aqua_app_owner")
    assert (
        app_database.execute(
            "SELECT version,checksum FROM app.schema_migrations WHERE version<=6 ORDER BY version"
        ).fetchall()
        == old
    )
    assert app_database.execute(
        "SELECT display_name,profile_revision,email_revision,auth_epoch FROM app.users WHERE id=%s",
        (owner,),
    ).fetchone() == ("Before identity actions", 8, 1, 0)
    assert app_database.execute(
        "SELECT is_active,revision FROM app.external_identities WHERE id=%s",
        (identity,),
    ).fetchone() == (True, 9)
    assert app_database.execute(
        "SELECT consumed_at IS NOT NULL,external_identity_revision FROM app.account_action_proofs WHERE id=%s",
        (proof,),
    ).fetchone() == (True, None)
    with pytest.raises(psycopg.errors.CheckViolation):
        with app_database.transaction():
            app_database.execute(
                "UPDATE app.account_action_proofs SET consumed_at=NULL WHERE id=%s",
                (proof,),
            )


def test_failed_seventh_migration_rolls_back_every_new_object_and_legacy_consumption(
    app_database,
):
    _, _, proof, old = legacy_six(app_database)
    broken = replace(migrations()[6], text=migrations()[6].text + "; SELECT 1/0;")
    with pytest.raises(MigrationError, match="rolled_back"):
        apply(app_database, (*migrations()[:6], broken))
    app_database.execute("SET ROLE aqua_app_owner")
    assert (
        app_database.execute(
            "SELECT version,checksum FROM app.schema_migrations ORDER BY version"
        ).fetchall()
        == old
    )
    assert app_database.execute(
        "SELECT to_regclass('app.account_security_requests'),to_regclass('app.user_notification_settings')"
    ).fetchone() == (None, None)
    assert app_database.execute(
        "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE id=%s",
        (proof,),
    ).fetchone() == (True,)
    app_database.execute("RESET ROLE")
    assert apply(app_database, migrations()[:7]) == 7


def test_new_request_fk_cannot_attach_another_owner_google_identity(identity_security):
    secure = identity_security
    client, _ = secure.client(linked=False)
    _, other = secure.client("B", linked=False)
    proof = secure.google_proof(client)
    request = client.post(
        PATH + "/password-enrollments", json={"proof_token": proof}
    ).json()
    with secure.world.storage.transaction() as conn:
        foreign = conn.execute(
            "SELECT id FROM app.external_identities WHERE user_id=%s", (other,)
        ).fetchone()[0]
    with pytest.raises(StorageUnavailable):
        with secure.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.account_security_requests SET source_google_identity_id=%s WHERE id=%s",
                (foreign, request["request_id"]),
            )
    with pytest.raises(StorageUnavailable):
        with secure.world.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.account_security_requests SET source_google_identity_id=NULL,source_google_identity_revision=NULL WHERE id=%s",
                (request["request_id"],),
            )


def test_auth_cleanup_remains_compatible_with_schema_six(app_database):
    owner, _, _, _ = legacy_six(app_database)
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute(
        "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE user_id=%s",
        (owner,),
    )
    app_database.execute(
        "UPDATE app.sessions SET created_at=now()-interval '2 hours',idle_expires_at=now()-interval '2 seconds',absolute_expires_at=now()-interval '1 second' WHERE user_id=%s",
        (owner,),
    )
    cleanup(app_database, AuthPolicy())
    assert app_database.execute(
        "SELECT count(*) FROM app.sessions WHERE user_id=%s", (owner,)
    ).fetchone() == (0,)
    assert app_database.execute(
        "SELECT count(*) FROM app.auth_challenges WHERE user_id=%s", (owner,)
    ).fetchone() == (0,)


@pytest.mark.parametrize("version", [1, 2])
def test_auth_cleanup_remains_compatible_before_mail_schema(app_database, version):
    assert apply(app_database, migrations()[:version]) == version
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute(
        "INSERT INTO app.auth_challenges(purpose,secret_digest,created_at,expires_at) VALUES('google_login',%s,now()-interval '2 minutes',now()-interval '1 second')",
        (b"x" * 32,),
    )
    cleanup(app_database, AuthPolicy())
    assert app_database.execute(
        "SELECT count(*) FROM app.auth_challenges"
    ).fetchone() == (0,)
