"""Only a fresh detached verification of this exact credential can issue proof."""

import pytest

from account.security_http import binding_cookie
from auth.sessions import new_token, session_cookie_name, token_digest
from security_action_fixtures import OLD, PATH


def reauth(account_security, challenge, **changes):
    return {
        "operation": "password_change",
        "challenge_id": challenge["challenge_id"],
        "challenge_token": challenge["challenge_token"],
        "password": OLD,
        **changes,
    }


def test_wrong_password_consumes_challenge_and_cannot_be_retried_correctly(
    account_security,
):
    client, owner = account_security.client()
    challenge = account_security.challenge(client)
    assert (
        client.post(
            PATH + "/reauth/password",
            json=reauth(
                account_security, challenge, password="A wrong synthetic password 18"
            ),
        ).status_code
        == 403
    )
    assert (
        client.post(
            PATH + "/reauth/password", json=reauth(account_security, challenge)
        ).status_code
        == 403
    )
    assert account_security.hasher.calls == ["verify"]
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (challenge["challenge_id"],),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
    assert account_security.proof(client)


@pytest.mark.parametrize(
    "change", ["binding", "secret", "session", "owner", "action", "expired", "legacy"]
)
def test_wrong_challenge_binding_is_denied_before_any_hash(account_security, change):
    client, owner = account_security.client()
    other, _ = account_security.client("B" if change == "owner" else "A")
    challenge = account_security.challenge(client)
    body = reauth(account_security, challenge)
    candidate, headers = client, {}
    if change in {"session", "owner"}:
        candidate = other
        headers = {
            "Cookie": session_cookie_name(account_security.world.settings)
            + "="
            + other.cookies.get(session_cookie_name(account_security.world.settings))
            + "; "
            + binding_cookie(account_security.world.settings)
            + "="
            + client.cookies.get(binding_cookie(account_security.world.settings))
        }
    elif change == "binding":
        headers = {
            "Cookie": session_cookie_name(account_security.world.settings)
            + "="
            + client.cookies.get(session_cookie_name(account_security.world.settings))
        }
    elif change == "secret":
        body["challenge_token"] = new_token()
    elif change == "action":
        body["operation"] = "sessions_revoke_all"
    else:
        with account_security.world.storage.transaction() as conn:
            if change == "expired":
                conn.execute(
                    "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
                    (challenge["challenge_id"],),
                )
            else:
                conn.execute(
                    "UPDATE app.auth_challenges SET account_operation=NULL,account_target_digest=NULL,account_auth_epoch=NULL WHERE id=%s",
                    (challenge["challenge_id"],),
                )
    assert (
        candidate.post(
            PATH + "/reauth/password", json=body, headers=headers
        ).status_code
        == 403
    )
    assert account_security.hasher.calls == [] and account_security.world.calls == []
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "change", ["hash", "changed_at", "epoch", "revoked", "disabled", "expiry"]
)
def test_credential_or_authority_change_during_hash_cannot_issue_a_proof(
    account_security, change
):
    client, owner = account_security.client()
    challenge = account_security.challenge(client)
    principal = account_security.principal(client)

    def change_state():
        with account_security.world.storage.transaction() as conn:
            if change == "hash":
                conn.execute(
                    "UPDATE app.password_credentials SET encoded_hash=%s WHERE user_id=%s",
                    (
                        account_security.hasher.encoded(
                            "A different synthetic password 82"
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
            elif change == "disabled":
                conn.execute(
                    "UPDATE app.users SET status='disabled' WHERE id=%s", (owner,)
                )
            else:
                conn.execute(
                    "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
                    (challenge["challenge_id"],),
                )

    account_security.hasher.on_verify = change_state
    assert client.post(
        PATH + "/reauth/password", json=reauth(account_security, challenge)
    ).status_code in {401, 403}
    with account_security.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (challenge["challenge_id"],),
        ).fetchone() == (True,)


@pytest.mark.parametrize(
    "change", ["owner", "session", "action", "expired", "changed_at", "forged"]
)
def test_wrong_proof_is_rejected_before_new_password_hashing(account_security, change):
    client, owner = account_security.client()
    other, _ = account_security.client("B" if change == "owner" else "A")
    proof = account_security.proof(
        client, "sessions_revoke_all" if change == "action" else "password_change"
    )
    if change in {"expired", "changed_at"}:
        with account_security.world.storage.transaction() as conn:
            if change == "expired":
                conn.execute(
                    "UPDATE app.account_action_proofs SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
                    (token_digest(proof),),
                )
            else:
                conn.execute(
                    "UPDATE app.password_credentials SET changed_at=clock_timestamp() WHERE user_id=%s",
                    (owner,),
                )
    candidate = other if change in {"owner", "session"} else client
    account_security.hasher.calls.clear()
    response = candidate.put(
        PATH + "/password",
        json={
            "proof_token": new_token() if change == "forged" else proof,
            "new_password": "A new synthetic proposed password 77",
        },
    )
    assert response.status_code == 403 and account_security.hasher.calls == []
    assert account_security.world.calls == []


@pytest.mark.parametrize("reactivated", [False, True])
def test_google_proof_is_unavailable_even_after_identity_reactivation(
    account_security, reactivated
):
    from test_account_proofs import verified_fixture

    client, _ = account_security.client()
    principal = account_security.principal(client)
    google_proof, _ = verified_fixture(
        account_security.world, principal, method="google"
    )
    from account.proof_consumption import check_proof

    with account_security.world.storage.transaction() as conn:
        check_proof(
            conn,
            account_security.world.policy,
            principal,
            "sessions_revoke_all",
            None,
            google_proof,
            method="google",
        )
        conn.execute(
            "UPDATE app.external_identities SET is_active=false,inactive_at=now(),revision=revision+1 WHERE user_id=%s",
            (principal.user["id"],),
        )
        if reactivated:
            conn.execute(
                "UPDATE app.external_identities SET is_active=true,inactive_at=NULL,revision=revision+1 WHERE user_id=%s",
                (principal.user["id"],),
            )
    # A once-valid proof cannot revive when the same tombstone is active again.
    response = client.post(
        PATH + "/session-revocations", json={"proof_token": "invalid"}
    )
    assert response.status_code == 422
    from account.security_actions import SecurityActions
    from workspace.errors import WorkspaceError

    with pytest.raises(WorkspaceError, match="proof_invalid"):
        SecurityActions(account_security.passwords).session(
            principal, None, google_proof
        )
    from account.proofs import consume_proof

    with pytest.raises(WorkspaceError, match="proof_invalid"):
        with account_security.world.storage.transaction() as conn:
            consume_proof(
                conn,
                account_security.world.policy,
                principal,
                "sessions_revoke_all",
                None,
                google_proof,
            )
    assert account_security.hasher.calls == []
