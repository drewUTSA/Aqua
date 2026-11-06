"""Deletion proof generations survive detached verification and replay races."""

from uuid import uuid4

import pytest

from account.proof_consumption import consume_proof
from auth.sessions import token_digest
from security_action_fixtures import OLD, PATH
from workspace.errors import WorkspaceError

OPERATIONS = ("history_delete", "account_delete")
FIELDS = ("privacy_epoch", "history_generation")


def target(operation, intent):
    return {"operation": operation, "target_intent_id": intent}


def begin(secure, client, owner, method, operation, intent):
    body = target(operation, intent)
    if method == "google":
        with secure.world.storage.transaction() as conn:
            identity = str(
                conn.execute(
                    "SELECT id FROM app.external_identities WHERE user_id=%s AND is_active ORDER BY id LIMIT 1",
                    (owner,),
                ).fetchone()[0]
            )
        response = client.post(
            PATH + "/reauth/google-challenges", json={**body, "identity_id": identity}
        )
    else:
        response = client.post(PATH + "/reauth-challenges", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def verify(secure, client, owner, method, operation, intent, challenge):
    body = {
        **target(operation, intent),
        "challenge_id": challenge["challenge_id"],
        "challenge_token": challenge["challenge_token"],
    }
    if method == "google":
        with secure.world.storage.transaction() as conn:
            subject, email = conn.execute(
                "SELECT subject,observed_email_key FROM app.external_identities WHERE user_id=%s AND is_active ORDER BY id LIMIT 1",
                (owner,),
            ).fetchone()
        body["credential"] = secure.assertion(
            challenge["nonce"], subject=subject, email=email
        )
    else:
        body["password"] = OLD
    return client.post(
        PATH + ("/reauth/google" if method == "google" else "/reauth/password"),
        json=body,
    )


def bump(secure, owner, field):
    assert field in FIELDS
    with secure.world.storage.transaction() as conn:
        conn.execute(f"UPDATE app.users SET {field}={field}+1 WHERE id=%s", (owner,))


def issue(secure, client, owner, method, operation, intent):
    challenge = begin(secure, client, owner, method, operation, intent)
    response = verify(secure, client, owner, method, operation, intent, challenge)
    assert response.status_code == 200, response.text
    return response.json()["proof_token"], challenge


def consume(secure, principal, operation, intent, proof):
    with secure.world.storage.transaction() as conn:
        consume_proof(
            conn,
            secure.passwords.auth_policy,
            principal,
            operation,
            intent,
            token_digest(proof),
        )


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("method", ("password", "google"))
def test_real_verifier_captures_current_snapshots_and_consumption_is_one_use(
    identity_security, operation, method
):
    secure = identity_security
    client, owner = secure.client(linked=method == "password")
    intent = str(uuid4())
    proof, challenge = issue(secure, client, owner, method, operation, intent)
    with secure.world.storage.transaction() as conn:
        current = conn.execute(
            "SELECT privacy_epoch,history_generation FROM app.users WHERE id=%s",
            (owner,),
        ).fetchone()
        captured = conn.execute(
            "SELECT c.account_privacy_epoch,c.account_history_generation,p.privacy_epoch,p.history_generation,p.method FROM app.auth_challenges c JOIN app.account_action_proofs p ON p.challenge_id=c.id WHERE c.id=%s",
            (challenge["challenge_id"],),
        ).fetchone()
        assert captured == (*current, *current, method)
    principal = secure.principal(client)
    consume(secure, principal, operation, intent, proof)
    with pytest.raises(WorkspaceError, match="proof_invalid"):
        consume(secure, principal, operation, intent, proof)
    assert secure.world.calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("method", ("password", "google"))
@pytest.mark.parametrize("field", FIELDS)
def test_generation_change_before_claim_denies_before_hash_or_provider_and_fresh_action_recovers(
    identity_security, operation, method, field
):
    secure = identity_security
    client, owner = secure.client(linked=method == "password")
    intent = str(uuid4())
    challenge = begin(secure, client, owner, method, operation, intent)
    bump(secure, owner, field)
    response = verify(secure, client, owner, method, operation, intent, challenge)
    assert response.status_code in {403, 409}
    assert secure.hasher.calls == [] and secure.provider_calls == []
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
    proof, _ = issue(secure, client, owner, method, operation, str(uuid4()))
    assert proof and secure.world.calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("method", ("password", "google"))
@pytest.mark.parametrize("field", FIELDS)
def test_generation_change_during_detached_verification_never_publishes_proof(
    identity_security, operation, method, field
):
    secure = identity_security
    client, owner = secure.client(linked=method == "password")
    intent = str(uuid4())
    challenge = begin(secure, client, owner, method, operation, intent)
    with secure.world.storage.transaction() as conn:
        observed = conn.execute(
            "SELECT observed_email_key,email_authoritative FROM app.external_identities WHERE user_id=%s ORDER BY id LIMIT 1",
            (owner,),
        ).fetchone()
    if method == "password":
        secure.hasher.on_verify = lambda: bump(secure, owner, field)
    else:
        secure.on_google = lambda: bump(secure, owner, field)
    response = verify(secure, client, owner, method, operation, intent, challenge)
    assert response.status_code in {403, 409}
    assert secure.hasher.calls == (["verify"] if method == "password" else [])
    assert len(secure.provider_calls) == (1 if method == "google" else 0)
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.account_action_proofs WHERE user_id=%s", (owner,)
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.auth_challenges WHERE id=%s",
            (challenge["challenge_id"],),
        ).fetchone() == (True,)
        assert (
            conn.execute(
                "SELECT observed_email_key,email_authoritative FROM app.external_identities WHERE user_id=%s ORDER BY id LIMIT 1",
                (owner,),
            ).fetchone()
            == observed
        )
    secure.hasher.on_verify = secure.on_google = None
    fresh_intent = str(uuid4())
    proof, _ = issue(secure, client, owner, method, operation, fresh_intent)
    consume(secure, secure.principal(client), operation, fresh_intent, proof)
    assert secure.world.calls == []


@pytest.mark.parametrize("operation", OPERATIONS)
@pytest.mark.parametrize("method", ("password", "google"))
@pytest.mark.parametrize("field", FIELDS)
def test_generation_change_after_proof_denies_consumption_and_cannot_be_rebound(
    identity_security, operation, method, field
):
    secure = identity_security
    client, owner = secure.client(linked=method == "password")
    intent = str(uuid4())
    proof, _ = issue(secure, client, owner, method, operation, intent)
    principal = secure.principal(client)
    bump(secure, owner, field)
    # Rehydrating the current session cannot bind an older proof to new floors.
    principal = secure.principal(client)
    with pytest.raises(WorkspaceError, match="proof_invalid"):
        consume(secure, principal, operation, intent, proof)
    with secure.world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (token_digest(proof),),
        ).fetchone() == (True,)
    fresh_intent = str(uuid4())
    fresh, _ = issue(secure, client, owner, method, operation, fresh_intent)
    consume(secure, secure.principal(client), operation, fresh_intent, fresh)


@pytest.mark.parametrize("method", ("password", "google"))
@pytest.mark.parametrize(
    "substitute", ("intent", "operation", "foreign_owner", "foreign_session")
)
def test_claim_substitution_never_starts_expensive_work_and_original_target_remains_valid(
    identity_security, method, substitute
):
    secure = identity_security
    client, owner = secure.client(linked=method == "password")
    other, other_owner = secure.client(
        "B" if substitute == "foreign_owner" else "A", linked=method == "password"
    )
    operation, intent = "history_delete", str(uuid4())
    challenge = begin(secure, client, owner, method, operation, intent)
    target_client, target_owner = (
        (other, other_owner) if substitute.startswith("foreign") else (client, owner)
    )
    response = verify(
        secure,
        target_client,
        target_owner,
        method,
        "account_delete" if substitute == "operation" else operation,
        str(uuid4()) if substitute == "intent" else intent,
        challenge,
    )
    assert response.status_code in {403, 409}
    assert secure.hasher.calls == [] and secure.provider_calls == []
    response = verify(secure, client, owner, method, operation, intent, challenge)
    assert response.status_code == 200, response.text


@pytest.mark.parametrize("method", ("password", "google"))
def test_issued_proof_cannot_cross_operations_or_intents(identity_security, method):
    secure = identity_security
    client, owner = secure.client(linked=method == "password")
    intent = str(uuid4())
    proof, _ = issue(secure, client, owner, method, "history_delete", intent)
    principal = secure.principal(client)
    for operation, candidate in (
        ("account_delete", intent),
        ("history_delete", str(uuid4())),
    ):
        with pytest.raises(WorkspaceError, match="proof_invalid"):
            consume(secure, principal, operation, candidate, proof)
    consume(secure, principal, "history_delete", intent, proof)
