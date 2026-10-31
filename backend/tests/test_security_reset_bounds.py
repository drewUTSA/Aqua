"""Current reset links use the existing live index, never a retained-history sweep."""

import pytest

from account.reset_invalidation import LIVE_RESETS_SQL
from auth.sessions import token_digest
from security_action_fixtures import NEW, PATH
from test_security_action_failures import seed_reset


def test_password_change_preserves_expired_reset_history_and_seeks_live_index(
    account_security, app_database
):
    client, owner = account_security.client()
    proof = account_security.proof(client)
    _, reset_id = seed_reset(account_security, owner)
    with account_security.world.storage.transaction() as conn:
        conn.execute(
            "INSERT INTO app.auth_challenges(user_id,purpose,secret_digest,target_email_key,password_auth_epoch,created_at,expires_at) SELECT %s,'password_reset',decode(md5('p10b-old-reset-'||n::text)||md5('p10b-old-reset-tail-'||n::text),'hex'),'a@gmail.com',0,now()-interval '2 hours',now()-interval '1 hour' FROM generate_series(1,5000)n",
            (owner,),
        )
    app_database.execute("SET ROLE aqua_app_owner")
    app_database.execute("ANALYZE app.auth_challenges")
    app_database.execute("RESET ROLE")
    with account_security.world.storage.transaction() as conn:
        instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        plan = conn.execute(
            "EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) " + LIVE_RESETS_SQL,
            ("a@gmail.com", instant, owner, 0, 4),
        ).fetchone()[0][0]["Plan"]

    def nodes(node):
        yield node
        for child in node.get("Plans", []):
            yield from nodes(child)

    assert plan["Actual Rows"] == 1
    assert any(
        node.get("Index Name") == "challenges_password_target" for node in nodes(plan)
    )
    assert plan.get("Shared Hit Blocks", 0) + plan.get("Shared Read Blocks", 0) <= 64
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
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE user_id=%s AND purpose='password_reset' AND expires_at<=now() AND consumed_at IS NULL",
            (owner,),
        ).fetchone() == (5000,)
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (1,)


@pytest.mark.parametrize("excess", ["tickets", "jobs"])
def test_unexpected_live_reset_or_mail_excess_rolls_back_fail_closed(
    account_security, excess
):
    client, owner = account_security.client()
    proof = account_security.proof(client)
    if excess == "jobs":
        _, reset_id = seed_reset(account_security, owner)
        with account_security.world.storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.account_mail(id,purpose,recipient_digest,ciphertext,challenge_id,expires_at) SELECT gen_random_uuid(),'reset_password',%s,%s,%s,now()+interval '1 hour' FROM generate_series(1,3)",
                (b"x" * 32, b"x" * 30, reset_id),
            )
    else:
        with account_security.world.storage.transaction() as conn:
            conn.execute(
                "INSERT INTO app.auth_challenges(user_id,purpose,secret_digest,target_email_key,password_auth_epoch,expires_at) SELECT %s,'password_reset',decode(md5('p10b-excess-reset-'||n::text)||md5('p10b-excess-reset-tail-'||n::text),'hex'),'a@gmail.com',0,now()+interval '20 minutes' FROM generate_series(1,4)n",
                (owner,),
            )
    response = client.put(
        PATH + "/password", json={"proof_token": proof, "new_password": NEW}
    )
    assert response.status_code == 503 and "set-cookie" not in response.headers
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='password_changed'"
        ).fetchone() == (0,)
