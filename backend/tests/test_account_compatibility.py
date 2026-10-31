"""P10a compatibility fences before method-removal operations can be enabled."""

from dataclasses import replace

import pytest

from auth.accounts import grant_state, preserve_approved_grant
from auth.config import AuthDenied
from auth.sessions import new_token, token_digest
from storage.migrate import apply, migrations


def identity(label="A"):
    return {
        "sub": "workspace-" + label,
        "email": label.lower() + "@gmail.com",
        "email_verified": True,
        "name": label,
        "picture": "",
    }


def test_inactive_google_identity_cannot_login_seed_or_authorize_derived_grant(world):
    a, owner = world.client(grant=False)
    policy = replace(world.policy, allowed_emails=frozenset({"a@gmail.com"}))
    with world.storage.transaction() as conn:
        preserve_approved_grant(conn, owner, policy, "workspace-A")
        assert grant_state(conn, owner, policy)[0]
        conn.execute(
            "UPDATE app.external_identities SET is_active=false,inactive_at=now() WHERE user_id=%s",
            (owner,),
        )
        assert not grant_state(conn, owner, policy)[0]
    with pytest.raises(AuthDenied):
        world.store.login(
            identity(),
            token_digest(new_token()),
            token_digest(new_token()),
            "fixture",
            world.settings,
        )
    with world.storage.transaction() as conn:
        conn.execute("DELETE FROM app.dataset_grants WHERE user_id=%s", (owner,))
        preserve_approved_grant(conn, owner, policy, "workspace-A")
        assert conn.execute(
            "SELECT count(*) FROM app.dataset_grants WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        conn.execute(
            "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s)",
            (owner, policy.dataset_key),
        )
        assert grant_state(conn, owner, policy)[0]
    assert a.get("/api/v1/me/methods").json()["google"]["linked"] is False


def test_final_google_session_transaction_rechecks_identity_after_resolution(
    world, monkeypatch
):
    import auth.store as module

    _, owner = world.client(grant=False)
    original = module.admit

    def deactivate(conn, policy, operation, *args, **kwargs):
        original(conn, policy, operation, *args, **kwargs)
        if operation == "account":
            conn.execute(
                "UPDATE app.external_identities SET is_active=false,inactive_at=now() WHERE user_id=%s",
                (owner,),
            )

    monkeypatch.setattr(module, "admit", deactivate)
    with pytest.raises(AuthDenied, match="identity_inactive"):
        world.store.login(
            identity(),
            token_digest(new_token()),
            token_digest(new_token()),
            "fixture",
            world.settings,
        )
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE user_id=%s", (owner,)
        ).fetchone() == (1,)


def test_additive_upgrade_preserves_profiles_primary_mail_preferences_and_provenance(
    app_database,
):
    assert apply(app_database, migrations()[:5]) == 5
    app_database.execute("SET ROLE aqua_app_owner")
    owner = app_database.execute(
        "INSERT INTO app.users(status,display_name,picture) VALUES('active','Existing profile','') RETURNING id"
    ).fetchone()[0]
    app_database.execute(
        "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) VALUES(%s,'existing@gmail.com','existing@gmail.com',now(),'google',true)",
        (owner,),
    )
    external = app_database.execute(
        "INSERT INTO app.external_identities(user_id,provider,issuer,subject) VALUES(%s,'google','https://accounts.google.com','existing') RETURNING id",
        (owner,),
    ).fetchone()[0]
    app_database.execute(
        "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) VALUES(%s,'synthetic','google_subject',%s,'existing')",
        (owner, external),
    )
    app_database.execute(
        'INSERT INTO app.user_preferences(user_id,revision,values) VALUES(%s,7,\'{"accent":"sage"}\')',
        (owner,),
    )
    app_database.execute("RESET ROLE")
    assert apply(app_database) == apply(app_database) == 8
    app_database.execute("SET ROLE aqua_app_owner")
    assert app_database.execute(
        "SELECT display_name,profile_revision FROM app.users WHERE id=%s", (owner,)
    ).fetchone() == ("Existing profile", 1)
    assert app_database.execute(
        "SELECT address,is_primary FROM app.user_emails WHERE user_id=%s", (owner,)
    ).fetchone() == ("existing@gmail.com", True)
    assert app_database.execute(
        "SELECT is_active,inactive_at,revision FROM app.external_identities WHERE id=%s",
        (external,),
    ).fetchone() == (True, None, 1)
    assert app_database.execute(
        "SELECT revision,values FROM app.user_preferences WHERE user_id=%s", (owner,)
    ).fetchone() == (7, {"accent": "sage"})
    assert app_database.execute(
        "SELECT approval_identity_id,revoked_at FROM app.dataset_grants WHERE user_id=%s",
        (owner,),
    ).fetchone() == (external, None)
