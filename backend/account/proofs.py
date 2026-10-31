"""One-use action challenges; ordinary login timestamps are never action proof."""

from dataclasses import dataclass, field

from account.authority import current_id, owned_target
from account.credentials import password_snapshot
from account.proof_consumption import consume_proof as consume_proof
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


def create_challenge(
    storage: Storage,
    policy: AuthPolicy,
    session: UserSession,
    operation: str,
    target: object,
    secret: bytes,
    binding: bytes,
    *,
    require_password: bool = False,
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
        # Authenticated ineligible attempts still spend the committed admission;
        # no credential lookup or challenge allocation precedes that budget.
        if require_password:
            password_snapshot(conn, session.user["id"])
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
