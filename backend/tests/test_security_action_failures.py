"""A failed mutation preserves proof/credential state; committed changes do not replay."""

import secrets
from uuid import UUID, uuid4

import pytest

from auth.mailconfig import MailUnavailable
from auth.mailoutbox import enqueue
from auth.sessions import token_digest
from security_action_fixtures import NEW, OLD, PATH


def seed_reset(account_security, owner):
    token = secrets.token_urlsafe(32)
    with account_security.world.storage.transaction() as conn:
        row = conn.execute(
            "INSERT INTO app.auth_challenges(user_id,purpose,secret_digest,target_email_key,password_auth_epoch,expires_at) VALUES(%s,'password_reset',%s,'a@gmail.com',0,now()+interval '30 minutes') RETURNING id,expires_at",
            (owner, token_digest(token)),
        ).fetchone()
        enqueue(
            conn,
            recipient="a@gmail.com",
            purpose="reset_password",
            token=token,
            expires_at=row[1],
            policy=account_security.passwords.mail_policy,
            challenge_id=UUID(str(row[0])),
        )
    return token, row[0]


@pytest.mark.parametrize("failure", ["mail", "database"])
def test_failure_after_credential_update_rolls_back_every_mutation_and_cookie_clear(
    account_security, monkeypatch, failure
):
    import account.security_actions as module

    client, owner = account_security.client()
    _, reset_id = seed_reset(account_security, owner)
    proof = account_security.proof(client)

    def fail(conn, **kwargs):
        enqueue(conn, **kwargs)
        if failure == "mail":
            raise MailUnavailable("synthetic private provider error must not escape")
        conn.execute("SELECT 1/0")

    monkeypatch.setattr(module, "enqueue", fail)
    response = client.put(
        PATH + "/password", json={"proof_token": proof, "new_password": NEW}
    )
    assert response.status_code == 503 and "private provider" not in response.text
    assert "set-cookie" not in response.headers and client.get(PATH).status_code == 200
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT u.auth_epoch,p.encoded_hash FROM app.users u JOIN app.password_credentials p ON p.user_id=u.id WHERE u.id=%s",
            (owner,),
        ).fetchone() == (0, account_security.hasher.encoded(OLD))
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.auth_challenges WHERE id=%s",
            (reset_id,),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT purpose FROM app.account_mail ORDER BY purpose"
        ).fetchall() == [("reset_password",)]
        assert conn.execute(
            "SELECT count(*) FROM app.password_hash_slots"
        ).fetchone() == (0,)
    monkeypatch.setattr(module, "enqueue", enqueue)
    assert (
        client.put(
            PATH + "/password", json={"proof_token": proof, "new_password": NEW}
        ).status_code
        == 200
    )
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (reset_id,),
        ).fetchone() == (True,)
        assert conn.execute("SELECT purpose FROM app.account_mail").fetchall() == [
            ("password_changed",)
        ]


def test_disabled_or_full_mandatory_notice_prevents_password_change(account_security):
    from dataclasses import replace

    client, owner = account_security.client()
    proof = account_security.proof(client)
    original = account_security.passwords.mail_policy
    account_security.passwords.mail_policy = replace(original, enabled=False)
    account_security.hasher.calls.clear()
    response = client.put(
        PATH + "/password", json={"proof_token": proof, "new_password": NEW}
    )
    assert response.status_code == 503 and account_security.hasher.calls == []
    account_security.passwords.mail_policy = replace(
        original, max_rows=1, max_pending=1
    )
    with account_security.world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.account_mail(id,purpose,recipient_digest,ciphertext,expires_at) VALUES(%s,'password_changed',%s,%s,now()+interval '1 hour')",
            (uuid4(), b"z" * 32, b"z" * 30),
        )
    assert (
        client.put(
            PATH + "/password", json={"proof_token": proof, "new_password": NEW}
        ).status_code
        == 503
    )
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)


@pytest.mark.parametrize(
    "change",
    ["hash", "changed_at", "epoch", "revoked", "proof_expired", "challenge_expired"],
)
def test_final_mutation_rechecks_authority_after_detached_new_hash(
    account_security, change
):
    client, owner = account_security.client()
    proof = account_security.proof(client)
    principal = account_security.principal(client)
    with account_security.world.storage.transaction() as conn:
        before = conn.execute(
            "SELECT u.auth_epoch,p.encoded_hash,p.changed_at FROM app.users u JOIN app.password_credentials p ON p.user_id=u.id WHERE u.id=%s",
            (owner,),
        ).fetchone()

    def invalidate():
        with account_security.world.storage.transaction() as conn:
            if change == "hash":
                conn.execute(
                    "UPDATE app.password_credentials SET encoded_hash=%s WHERE user_id=%s",
                    (
                        account_security.hasher.encoded(
                            "An intervening password value 31"
                        ),
                        owner,
                    ),
                )
            elif change == "changed_at":
                conn.execute(
                    "UPDATE app.password_credentials SET changed_at=clock_timestamp() WHERE user_id=%s",
                    (owner,),
                )
            elif change == "epoch":
                conn.execute(
                    "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
                )
            elif change == "revoked":
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=now() WHERE token_digest=%s",
                    (principal.token_digest,),
                )
            elif change == "proof_expired":
                conn.execute(
                    "UPDATE app.account_action_proofs SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
                    (token_digest(proof),),
                )
            else:
                conn.execute(
                    "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE id=(SELECT challenge_id FROM app.account_action_proofs WHERE secret_digest=%s)",
                    (token_digest(proof),),
                )

    account_security.hasher.on_hash = invalidate
    assert client.put(
        PATH + "/password", json={"proof_token": proof, "new_password": NEW}
    ).status_code in {401, 403}
    assert account_security.hasher.calls == ["verify", "hash"]
    with account_security.world.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
        if change in {"proof_expired", "challenge_expired"}:
            assert (
                conn.execute(
                    "SELECT u.auth_epoch,p.encoded_hash,p.changed_at FROM app.users u JOIN app.password_credentials p ON p.user_id=u.id WHERE u.id=%s",
                    (owner,),
                ).fetchone()
                == before
            )
            assert conn.execute(
                "SELECT revoked_at IS NULL FROM app.sessions WHERE token_digest=%s",
                (principal.token_digest,),
            ).fetchone() == (True,)


def test_password_mutation_replay_cannot_send_another_notice_or_auto_sign_in(
    account_security,
):
    from account.security_actions import SecurityActions
    from workspace.errors import WorkspaceError

    client, _ = account_security.client()
    principal = account_security.principal(client)
    proof = account_security.proof(client)
    actions = SecurityActions(account_security.passwords)
    assert actions.password(principal, token_digest(proof), NEW)[
        "current_session_revoked"
    ]
    with pytest.raises(WorkspaceError):
        actions.password(principal, token_digest(proof), NEW)
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='password_changed'"
        ).fetchone() == (1,)
        assert conn.execute(
            "SELECT count(*) FROM app.sessions WHERE revoked_at IS NULL AND auth_epoch=1"
        ).fetchone() == (0,)
