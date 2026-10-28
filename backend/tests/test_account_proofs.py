"""Future action proofs cannot substitute a login timestamp or cross owners."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from account.proofs import claim_challenge, consume_proof, create_challenge
from account.policy import target_digest
from auth.config import AuthLimited
from auth.sessions import new_token, session_cookie_name, token_digest
from auth.security import UserSession
from storage.pool import Storage
from workspace.errors import WorkspaceError


def principal(world, client):
    raw = client.cookies.get(session_cookie_name(world.settings))
    current = world.store.authenticate(token_digest(raw))
    return UserSession(
        current.user,
        "",
        token_digest(raw),
        current.can_query,
        current.grant_version,
        current.auth_epoch,
        current.dataset_key,
    )


def ticket(world, session, operation="sessions_revoke_all", target=None):
    secret, binding = token_digest(new_token()), token_digest(new_token())
    challenge = create_challenge(
        world.storage, world.policy, session, operation, target, secret, binding
    )
    return challenge, secret, binding


def verified_fixture(world, session):
    """Synthetic verifier output only; production deliberately has no issuer."""
    challenge, secret, binding = ticket(world, session)
    claimed = claim_challenge(
        world.storage,
        world.policy,
        session,
        challenge,
        "sessions_revoke_all",
        None,
        secret,
        binding,
    )
    proof = token_digest(new_token())
    with world.storage.transaction() as conn:
        identity = conn.execute(
            "SELECT id FROM app.external_identities WHERE user_id=%s AND is_active",
            (session.user["id"],),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO app.account_action_proofs(user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,external_identity_id,created_at,expires_at) "
            "VALUES(%s,%s,%s,%s,%s,'sessions_revoke_all',%s,'google',%s,statement_timestamp(),statement_timestamp()+interval '240 seconds')",
            (
                claimed.owner,
                claimed.session_id,
                challenge,
                proof,
                claimed.auth_epoch,
                target_digest("sessions_revoke_all"),
                identity,
            ),
        )
    return proof, challenge


def test_claim_binds_session_action_target_secret_browser_binding_and_epoch(world):
    # Exercise each binding in one fixture; the production five-attempt budget
    # is verified separately and would otherwise stop this adversarial matrix.
    world.policy = replace(world.policy, action_account_limit=30)
    a, _ = world.client(grant=False)
    another, _ = world.client(grant=False)
    b, _ = world.client("B", grant=False)
    session = principal(world, a)
    challenge, secret, binding = ticket(world, session)
    for candidate, action, supplied_secret, supplied_binding in [
        (principal(world, another), "sessions_revoke_all", secret, binding),
        (principal(world, b), "sessions_revoke_all", secret, binding),
        (session, "google_link", secret, binding),
        (session, "sessions_revoke_all", b"z" * 32, binding),
        (session, "sessions_revoke_all", secret, b"z" * 32),
    ]:
        with pytest.raises(WorkspaceError, match="proof_invalid"):
            claim_challenge(
                world.storage,
                world.policy,
                candidate,
                challenge,
                action,
                None,
                supplied_secret,
                supplied_binding,
            )
    claimed = claim_challenge(
        world.storage,
        world.policy,
        session,
        challenge,
        "sessions_revoke_all",
        None,
        secret,
        binding,
    )
    assert (
        claimed.owner == session.user["id"] and claimed.auth_epoch == session.auth_epoch
    )
    with pytest.raises(WorkspaceError, match="proof_invalid"):
        claim_challenge(
            world.storage,
            world.policy,
            session,
            challenge,
            "sessions_revoke_all",
            None,
            secret,
            binding,
        )
    assert "target_digest" not in repr(claimed)


def test_foreign_target_is_denied_after_nonrefundable_durable_admission(world):
    a, owner = world.client(grant=False)
    b, _ = world.client("B", grant=False)
    foreign = b.get("/api/v1/me/sessions").json()["items"][0]["id"]
    session = principal(world, a)
    for _ in range(world.policy.action_account_limit):
        with pytest.raises(WorkspaceError, match="not_found"):
            ticket(world, session, "session_revoke", foreign)
    with pytest.raises(AuthLimited):
        ticket(world, session)
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT count(*) FROM app.auth_challenges WHERE user_id=%s AND account_operation IS NOT NULL",
            (owner,),
        ).fetchone() == (0,)
        assert conn.execute(
            "SELECT hits FROM app.auth_admission WHERE scope='action:account'"
        ).fetchone() == (5,)


def test_proof_consumption_rolls_back_with_the_mutation_and_replay_denies(world):
    a, _ = world.client(grant=False)
    session = principal(world, a)
    proof, _ = verified_fixture(world, session)
    with pytest.raises(RuntimeError, match="synthetic mutation failure"):
        with world.storage.transaction() as conn:
            consume_proof(
                conn, world.policy, session, "sessions_revoke_all", None, proof
            )
            raise RuntimeError("synthetic mutation failure")
    with world.storage.transaction() as conn:
        consume_proof(conn, world.policy, session, "sessions_revoke_all", None, proof)
    with pytest.raises(WorkspaceError, match="proof_invalid"):
        with world.storage.transaction() as conn:
            consume_proof(
                conn, world.policy, session, "sessions_revoke_all", None, proof
            )


@pytest.mark.parametrize(
    "change",
    [
        "proof_expired",
        "challenge_expired",
        "identity_inactive",
        "epoch",
        "revoked",
        "wrong_action",
        "other_session",
    ],
)
def test_stale_or_differently_bound_proofs_never_become_authority(world, change):
    a, owner = world.client(grant=False)
    another, _ = world.client(grant=False)
    session = principal(world, a)
    proof, challenge = verified_fixture(world, session)
    with world.storage.transaction() as conn:
        if change == "proof_expired":
            conn.execute(
                "UPDATE app.account_action_proofs SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE secret_digest=%s",
                (proof,),
            )
        elif change == "challenge_expired":
            conn.execute(
                "UPDATE app.auth_challenges SET created_at=now()-interval '5 minutes',expires_at=now()-interval '1 second' WHERE id=%s",
                (challenge,),
            )
        elif change == "identity_inactive":
            conn.execute(
                "UPDATE app.external_identities SET is_active=false,inactive_at=now() WHERE user_id=%s",
                (owner,),
            )
        elif change == "epoch":
            conn.execute(
                "UPDATE app.users SET auth_epoch=auth_epoch+1 WHERE id=%s", (owner,)
            )
        elif change == "revoked":
            conn.execute(
                "UPDATE app.sessions SET revoked_at=now() WHERE user_id=%s", (owner,)
            )
    if change == "other_session":
        session = principal(world, another)
    with pytest.raises(WorkspaceError):
        with world.storage.transaction() as conn:
            consume_proof(
                conn,
                world.policy,
                session,
                "google_link" if change == "wrong_action" else "sessions_revoke_all",
                None,
                proof,
            )


def test_parallel_proof_consumption_across_storage_instances_has_one_winner(world):
    a, _ = world.client(grant=False)
    session = principal(world, a)
    proof, _ = verified_fixture(world, session)
    other = Storage(replace(world.storage.settings, max_connections=1))

    def consume(storage):
        try:
            with storage.transaction() as conn:
                consume_proof(
                    conn, world.policy, session, "sessions_revoke_all", None, proof
                )
            return "accepted"
        except WorkspaceError:
            return "denied"

    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            assert sorted(workers.map(consume, [world.storage, other])) == [
                "accepted",
                "denied",
            ]
    finally:
        other.close()


def test_recovered_proof_rows_are_consumed_by_the_compatible_restore_fence(
    world, app_database
):
    from pathlib import Path

    a, _ = world.client(grant=False)
    session = principal(world, a)
    proof, _ = verified_fixture(world, session)
    fence = Path(__file__).resolve().parents[2] / "ops/appdb/restore_session_fence.sql"
    app_database.execute(fence.read_text())
    app_database.execute("RESET ROLE")
    assert a.get("/api/v1/me").status_code == 401
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT consumed_at IS NOT NULL FROM app.account_action_proofs WHERE secret_digest=%s",
            (proof,),
        ).fetchone() == (True,)
