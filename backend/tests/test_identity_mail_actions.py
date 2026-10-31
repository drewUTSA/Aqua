"""First password and primary-mail changes require distinct exact mailbox proof."""

from dataclasses import replace
import pytest

from account.security_http import identity_cookie
from auth.mailconfig import MailUnavailable
from auth.sessions import new_token, token_digest
from security_action_fixtures import NEW, PATH
from test_identity_methods import account_state


def start_email(secure, client, target="new-primary@example.invalid"):
    proof = secure.password_proof(client, "email_change", target)
    response = client.post(
        PATH + "/email-change-requests",
        json={"proof_token": proof, "new_email": target},
    )
    assert response.status_code == 200, response.text
    request = response.json()
    tokens = secure.mail_tokens(request["request_id"])
    return {
        "proof_token": proof,
        "request_id": request["request_id"],
        "request_token": request["request_token"],
        "email_token": tokens["email_change_new"],
        "old_email_token": tokens["email_change_old"],
    }


def start_password(secure, client):
    proof = secure.google_proof(client)
    response = client.post(PATH + "/password-enrollments", json={"proof_token": proof})
    assert response.status_code == 200, response.text
    request = response.json()
    tokens = secure.mail_tokens(request["request_id"])
    return {
        "proof_token": proof,
        "request_id": request["request_id"],
        "request_token": request["request_token"],
        "email_token": tokens["password_add"],
        "new_password": NEW,
    }


def test_first_password_requires_primary_mail_and_google_and_costs_four_admissions(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    foreign, other = secure.client("B", linked=False)
    before_other = account_state(secure, other)
    secure.passwords.auth_policy = replace(
        secure.passwords.auth_policy, action_account_limit=5, action_global_limit=30
    )
    body = start_password(secure, client)
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(body["proof_token"]),),
        ).fetchone() == (True,)
    response = client.post(PATH + "/password", json=body)
    assert (
        response.status_code == 200
        and response.json()["password_added"]
        and client.get(PATH).status_code == 401
    )
    assert (
        foreign.get(PATH).status_code == 200
        and account_state(secure, other) == before_other
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT encoded_hash FROM app.password_credentials WHERE user_id=%s",
            (owner,),
        ).fetchone() == (secure.hasher.encoded(NEW),)
        assert conn.execute(
            "SELECT purpose,challenge_id FROM app.account_mail"
        ).fetchall() == [("password_added", None)]
        assert conn.execute(
            "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
        ).fetchone() == (4,)
    assert secure.hasher.calls == ["hash"] and len(secure.provider_calls) == 1


@pytest.mark.parametrize(
    "change", ["mail", "request_secret", "binding", "owner", "session", "proof"]
)
def test_first_password_wrong_authority_never_reaches_hash(identity_security, change):
    secure = identity_security
    client, owner = secure.client(linked=False)
    other, _ = secure.client("B" if change == "owner" else "A", linked=False)
    body = start_password(secure, client)
    if change == "mail":
        body["email_token"] = "z" * 43
    elif change == "request_secret":
        body["request_token"] = new_token()
    elif change == "proof":
        body["proof_token"] = new_token()
    elif change == "binding":
        client.cookies.delete(
            identity_cookie(secure.world.settings), domain="workspace.fixture", path="/"
        )
    candidate = other if change in {"owner", "session"} else client
    assert candidate.post(PATH + "/password", json=body).status_code == 403
    assert secure.hasher.calls == []
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)


@pytest.mark.parametrize(
    "change",
    [
        "proof_expired",
        "request_expired",
        "mail_expired",
        "identity_revision",
        "epoch",
        "session",
        "primary_revision",
        "intervening_password",
    ],
)
def test_detached_enrollment_hash_cannot_commit_after_authority_changes(
    identity_security, change
):
    secure = identity_security
    client, owner = secure.client(linked=False)
    principal = secure.principal(client)
    body = start_password(secure, client)

    def mutate():
        with secure.world.storage.transaction() as conn:
            if change == "proof_expired":
                conn.execute(
                    "UPDATE app.account_action_proofs SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
                    (token_digest(body["proof_token"]),),
                )
            elif change == "request_expired":
                conn.execute(
                    "UPDATE app.account_security_requests SET created_at=now()-interval '30 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
                    (body["request_id"],),
                )
            elif change == "mail_expired":
                conn.execute(
                    "UPDATE app.auth_challenges SET created_at=now()-interval '30 minutes',expires_at=now()-interval '1 second' WHERE account_request_id=%s",
                    (body["request_id"],),
                )
            elif change == "identity_revision":
                conn.execute(
                    "UPDATE app.external_identities SET revision=revision+1 WHERE user_id=%s",
                    (owner,),
                )
            elif change == "epoch":
                conn.execute(
                    "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
                )
            elif change == "session":
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=now() WHERE token_digest=%s",
                    (principal.token_digest,),
                )
            elif change == "primary_revision":
                conn.execute(
                    "UPDATE app.users SET email_revision=email_revision+1 WHERE id=%s",
                    (owner,),
                )
            else:
                conn.execute(
                    "INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version) VALUES(%s,%s,1)",
                    (owner, secure.hasher.encoded("An intervening password 58")),
                )

    secure.hasher.on_hash = mutate
    assert client.post(PATH + "/password", json=body).status_code in {401, 403, 409}
    assert secure.hasher.calls == ["hash"]
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(body["proof_token"]),),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='password_added'"
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT count(*) FROM app.password_credentials WHERE user_id=%s", (owner,)
        ).fetchone() == (int(change == "intervening_password"),)


def test_email_change_requires_both_audiences_then_changes_only_canonical_primary(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    foreign, other = secure.client("B")
    before_other = account_state(secure, other)
    body = start_email(secure, client)
    assert body["email_token"] != body["old_email_token"]
    swapped = {
        **body,
        "email_token": body["old_email_token"],
        "old_email_token": body["email_token"],
    }
    assert client.put(PATH + "/email", json=swapped).status_code == 403
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT bool_and(consumed_at IS NULL) FROM app.auth_challenges WHERE account_request_id=%s",
            (body["request_id"],),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary",
            (owner,),
        ).fetchone() == ("a@gmail.com",)
    assert (
        client.put(PATH + "/email", json=body).status_code == 200
        and client.get(PATH).status_code == 401
    )
    assert (
        foreign.get(PATH).status_code == 200
        and account_state(secure, other) == before_other
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT profile_revision,email_revision,auth_epoch FROM app.users WHERE id=%s",
            (owner,),
        ).fetchone() == (2, 2, 1)
        assert conn.execute(
            "SELECT email_key,is_primary FROM app.user_emails WHERE user_id=%s ORDER BY email_key",
            (owner,),
        ).fetchall() == [("a@gmail.com", False), ("new-primary@example.invalid", True)]
        assert conn.execute(
            "SELECT observed_email_key FROM app.external_identities WHERE user_id=%s",
            (owner,),
        ).fetchone() == ("a@gmail.com",)
        assert conn.execute(
            "SELECT purpose,challenge_id FROM app.account_mail ORDER BY recipient_digest"
        ).fetchall() == [("email_changed", None), ("email_changed", None)]


def test_mail_delivery_delay_requires_new_proof_without_rebinding_pending_request(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    body = start_email(secure, client)
    cookie = client.cookies.get(identity_cookie(secure.world.settings))
    with secure.world.storage.transaction() as conn:
        conn.execute(
            "UPDATE app.account_action_proofs SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
            (token_digest(body["proof_token"]),),
        )
    assert client.put(PATH + "/email", json=body).status_code == 403
    body["proof_token"] = secure.password_proof(
        client, "email_change", "new-primary@example.invalid"
    )
    assert client.cookies.get(identity_cookie(secure.world.settings)) == cookie
    assert client.put(PATH + "/email", json=body).status_code == 200
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT auth_epoch FROM app.users WHERE id=%s", (owner,)
        ).fetchone() == (1,)


@pytest.mark.parametrize("failure", ["mail", "database", "capacity"])
def test_final_mail_change_failure_preserves_proofs_tickets_primary_and_cookie(
    identity_security, monkeypatch, failure
):
    secure = identity_security
    client, owner = secure.client()
    body = start_email(secure, client)
    before = account_state(secure, owner)
    if failure == "capacity":
        secure.passwords.mail_policy = replace(
            secure.passwords.mail_policy, max_rows=3, max_pending=3
        )
    else:
        import account.google_methods as module

        original = module.enqueue

        def fail(conn, **kwargs):
            original(conn, **kwargs)
            if failure == "mail":
                raise MailUnavailable("synthetic notice failure")
            conn.execute("SELECT 1/0")

        monkeypatch.setattr(module, "enqueue", fail)
    response = client.put(PATH + "/email", json=body)
    assert (
        response.status_code == 503
        and "set-cookie" not in response.headers
        and account_state(secure, owner) == before
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(body["proof_token"]),),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT bool_and(consumed_at IS NULL) FROM app.auth_challenges WHERE account_request_id=%s",
            (body["request_id"],),
        ).fetchone() == (True,)
        assert conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose='email_changed'"
        ).fetchone() == (0,)


def test_second_mail_job_capacity_failure_rolls_back_entire_pending_request(
    identity_security,
):
    secure = identity_security
    client, _ = secure.client()
    proof = secure.password_proof(client, "email_change", "new-primary@example.invalid")
    secure.passwords.mail_policy = replace(
        secure.passwords.mail_policy, max_rows=1, max_pending=1
    )
    assert (
        client.post(
            PATH + "/email-change-requests",
            json={"proof_token": proof, "new_email": "new-primary@example.invalid"},
        ).status_code
        == 503
    )
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_security_requests"
        ).fetchone() == (0,)
        assert conn.execute("SELECT count(*) FROM app.account_mail").fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)


def test_email_unique_collision_after_mail_is_verified_never_merges_accounts(
    identity_security,
):
    secure = identity_security
    client, owner = secure.client()
    body = start_email(secure, client)
    with secure.world.storage.transaction() as conn:
        foreign = conn.execute(
            "INSERT INTO app.users(status) VALUES('active') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) VALUES(%s,'new-primary@example.invalid','new-primary@example.invalid',now(),'email',true)",
            (foreign,),
        )
    assert client.put(PATH + "/email", json=body).status_code == 409
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary",
            (owner,),
        ).fetchone() == ("a@gmail.com",)
        assert conn.execute(
            "SELECT user_id FROM app.user_emails WHERE email_key='new-primary@example.invalid'"
        ).fetchone() == (foreign,)
