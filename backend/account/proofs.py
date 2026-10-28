"""Fail-closed foundations for later recent-proof verification and actions.

No route mounts these operations and no proof issuer exists in P10a. Detached
password/Google verification and its credential-snapshot recheck are a later
slice. This module cannot treat a recent login, session timestamp or browser
claim as a successfully verified action proof.
"""

from dataclasses import dataclass, field

from psycopg import Connection

from account.policy import (
    MAX_CHALLENGES,
    OWNER_CHALLENGES,
    PROOF_SECONDS,
    digest,
    identifier,
    target_digest,
)
from auth.admission import admit
from auth.config import AuthLimited, AuthPolicy
from auth.security import UserSession
from storage.pool import Storage
from workspace.database import guard
from workspace.errors import WorkspaceError

LOCK = 1095848265


@dataclass(frozen=True)
class ClaimedChallenge:
    id: str
    owner: str
    session_id: str
    auth_epoch: int
    operation: str
    target_digest: bytes = field(repr=False)


def owned_target(
    conn: Connection, session: UserSession, operation: str, target: object
) -> None:
    """Check owned resources before issuing challenges or doing costly work."""
    if operation == "google_unlink":
        found = conn.execute(
            "SELECT id FROM app.external_identities WHERE user_id=%s AND id=%s AND is_active",
            (session.user["id"], target),
        ).fetchone()
    elif operation == "session_revoke":
        found = conn.execute(
            "SELECT id FROM app.sessions WHERE user_id=%s AND id=%s AND auth_epoch=%s "
            "AND revoked_at IS NULL AND idle_expires_at>clock_timestamp() "
            "AND absolute_expires_at>clock_timestamp()",
            (session.user["id"], target, session.auth_epoch),
        ).fetchone()
    else:
        return
    if found is None:
        raise WorkspaceError("not_found", 404)


def current_id(conn: Connection, session: UserSession, policy: AuthPolicy) -> str:
    guard(conn, session, policy)
    return str(
        conn.execute(
            "SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s",
            (session.user["id"], session.token_digest),
        ).fetchone()[0]
    )


def create_challenge(
    storage: Storage,
    policy: AuthPolicy,
    session: UserSession,
    operation: str,
    target: object,
    secret: bytes,
    binding: bytes,
) -> str:
    """Commit durable admission before any later detached verifier can start.

    The caller supplies digests of independently generated opaque secrets, not
    raw browser values or a caller-controlled owner. No verifier is called here.
    """
    bound, secret, binding = (
        target_digest(operation, target),
        digest(secret),
        digest(binding),
    )
    with storage.transaction() as conn:
        current_id(conn, session, policy)
        admit(conn, policy, "action", account_id=session.user["id"])
    with storage.transaction() as conn:
        sid = current_id(conn, session, policy)
        owned_target(conn, session, operation, target)
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        conn.execute(
            "DELETE FROM app.auth_challenges WHERE id IN (SELECT id FROM app.auth_challenges "
            "WHERE account_operation IS NOT NULL AND expires_at<=clock_timestamp() "
            "ORDER BY expires_at,id LIMIT %s FOR UPDATE SKIP LOCKED)",
            (policy.cleanup_batch,),
        )
        # The two bounded index scans never evict live replay tombstones.
        total = conn.execute(
            "SELECT id FROM app.auth_challenges WHERE account_operation IS NOT NULL LIMIT %s",
            (MAX_CHALLENGES,),
        ).fetchall()
        owned = conn.execute(
            "SELECT id FROM app.auth_challenges WHERE user_id=%s AND account_operation IS NOT NULL LIMIT %s",
            (session.user["id"], OWNER_CHALLENGES),
        ).fetchall()
        if len(total) >= MAX_CHALLENGES or len(owned) >= OWNER_CHALLENGES:
            raise AuthLimited(60)
        return str(
            conn.execute(
                "INSERT INTO app.auth_challenges(purpose,user_id,session_id,secret_digest,binding_digest,"
                "account_operation,account_target_digest,account_auth_epoch,created_at,expires_at) "
                "VALUES('reauth',%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),"
                "statement_timestamp()+%s*interval '1 second') RETURNING id",
                (
                    session.user["id"],
                    sid,
                    secret,
                    binding,
                    operation,
                    bound,
                    session.auth_epoch,
                    PROOF_SECONDS,
                ),
            ).fetchone()[0]
        )


def claim_challenge(
    storage: Storage,
    policy: AuthPolicy,
    session: UserSession,
    challenge_id: str,
    operation: str,
    target: object,
    secret: bytes,
    binding: bytes,
) -> ClaimedChallenge:
    """Consume before detached verification; failure/timeout cannot replay it."""
    bound, secret, binding = (
        target_digest(operation, target),
        digest(secret),
        digest(binding),
    )
    challenge_id = identifier(challenge_id)
    with storage.transaction() as conn:
        current_id(conn, session, policy)
        admit(conn, policy, "action", account_id=session.user["id"])
    with storage.transaction() as conn:
        sid = current_id(conn, session, policy)
        owned_target(conn, session, operation, target)
        row = conn.execute(
            "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() "
            "WHERE id=%s AND purpose='reauth' AND user_id=%s AND session_id=%s "
            "AND secret_digest=%s AND binding_digest=%s AND account_operation=%s "
            "AND account_target_digest=%s AND account_auth_epoch=%s "
            "AND consumed_at IS NULL AND expires_at>clock_timestamp() RETURNING id",
            (
                challenge_id,
                session.user["id"],
                sid,
                secret,
                binding,
                operation,
                bound,
                session.auth_epoch,
            ),
        ).fetchone()
        if row is None:
            raise WorkspaceError("proof_invalid", 403)
        return ClaimedChallenge(
            str(row[0]), session.user["id"], sid, session.auth_epoch, operation, bound
        )


def consume_proof(
    conn: Connection,
    policy: AuthPolicy,
    session: UserSession,
    operation: str,
    target: object,
    secret: bytes,
) -> None:
    """Consume in the SAME transaction as a later authorized security mutation.

    Raising/rolling back that mutation also rolls back consumption. Locks follow
    user, session, challenge, proof order. Fresh method state is checked again;
    epoch/session/action/target mismatches are never upgraded to a new ticket.
    """
    bound, secret = target_digest(operation, target), digest(secret)
    sid = current_id(conn, session, policy)
    owned_target(conn, session, operation, target)
    # Challenge cleanup also takes challenge before cascading into proof rows.
    # Preserve that lock order so future mutation rollback/cleanup cannot deadlock.
    challenge = conn.execute(
        "SELECT c.id FROM app.auth_challenges c JOIN app.account_action_proofs p "
        "ON p.challenge_id=c.id WHERE p.user_id=%s AND p.session_id=%s "
        "AND p.secret_digest=%s AND c.user_id=p.user_id AND c.session_id=p.session_id "
        "AND c.purpose='reauth' AND c.account_operation=%s AND c.account_target_digest=%s "
        "AND c.account_auth_epoch=%s AND c.consumed_at IS NOT NULL "
        "AND c.expires_at>clock_timestamp() FOR UPDATE OF c",
        (session.user["id"], sid, secret, operation, bound, session.auth_epoch),
    ).fetchone()
    if challenge is None:
        raise WorkspaceError("proof_invalid", 403)
    row = conn.execute(
        "UPDATE app.account_action_proofs p SET consumed_at=clock_timestamp() "
        "WHERE p.user_id=%s AND p.session_id=%s AND p.auth_epoch=%s "
        "AND p.operation=%s AND p.target_digest=%s AND p.secret_digest=%s "
        "AND p.consumed_at IS NULL AND p.expires_at>clock_timestamp() "
        "AND EXISTS(SELECT 1 FROM app.auth_challenges c WHERE c.id=p.challenge_id "
        "AND c.purpose='reauth' AND c.user_id=p.user_id AND c.session_id=p.session_id "
        "AND c.account_operation=p.operation AND c.account_target_digest=p.target_digest "
        "AND c.account_auth_epoch=p.auth_epoch AND c.consumed_at IS NOT NULL "
        "AND c.expires_at>clock_timestamp()) "
        "AND ((p.method='password' AND EXISTS(SELECT 1 FROM app.password_credentials k "
        "WHERE k.user_id=p.user_id AND k.changed_at=p.password_changed_at)) "
        "OR (p.method='google' AND EXISTS(SELECT 1 FROM app.external_identities e "
        "WHERE e.user_id=p.user_id AND e.id=p.external_identity_id AND e.is_active))) RETURNING p.id",
        (session.user["id"], sid, session.auth_epoch, operation, bound, secret),
    ).fetchone()
    if row is None:
        raise WorkspaceError("proof_invalid", 403)
