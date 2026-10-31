"""One-use action challenges; ordinary login timestamps are never action proof."""

from dataclasses import dataclass, field
from datetime import datetime

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
    created_at: datetime | None = None
    expires_at: datetime | None = None
    google_identity_id: str | None = None
    google_identity_revision: int | None = None


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
    google_identity: str | None = None,
) -> str:
    """Commit durable admission before any later detached verifier can start.

    The caller supplies digests of independently generated opaque secrets, not
    raw browser values or a caller-controlled owner. No verifier is called here.
    """
    secret, binding = digest(secret), digest(binding)
    with storage.transaction() as conn:
        current_id(conn, session, policy)
        admit(conn, policy, "action", account_id=session.user["id"])
    with storage.transaction() as conn:
        sid = current_id(conn, session, policy)
        target = target(conn) if callable(target) else target
        bound = target_digest(operation, target)
        # Authenticated ineligible attempts still spend the committed admission;
        # no credential lookup or challenge allocation precedes that budget.
        if require_password:
            password_snapshot(conn, session.user["id"])
        google_revision = None
        if google_identity is not None:
            found = conn.execute(
                "SELECT revision FROM app.external_identities WHERE user_id=%s AND id=%s AND is_active",
                (session.user["id"], identifier(google_identity)),
            ).fetchone()
            if found is None:
                raise WorkspaceError("method_unavailable", 403)
            google_revision = found[0]
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
                "account_operation,account_target_digest,account_auth_epoch,account_google_identity_id,account_google_identity_revision,created_at,expires_at) "
                "VALUES('reauth',%s,%s,%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),"
                "statement_timestamp()+%s*interval '1 second') RETURNING id",
                (
                    session.user["id"],
                    sid,
                    secret,
                    binding,
                    operation,
                    bound,
                    session.auth_epoch,
                    google_identity,
                    google_revision,
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
    *,
    google: bool = False,
) -> ClaimedChallenge:
    """Consume before detached verification; failure/timeout cannot replay it."""
    secret, binding = digest(secret), digest(binding)
    challenge_id = identifier(challenge_id)
    with storage.transaction() as conn:
        current_id(conn, session, policy)
        admit(conn, policy, "action", account_id=session.user["id"])
    with storage.transaction() as conn:
        sid = current_id(conn, session, policy)
        target = target(conn) if callable(target) else target
        bound = target_digest(operation, target)
        owned_target(conn, session, operation, target)
        row = conn.execute(
            "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() "
            "WHERE id=%s AND purpose='reauth' AND user_id=%s AND session_id=%s "
            "AND secret_digest=%s AND binding_digest=%s AND account_operation=%s "
            "AND account_target_digest=%s AND account_auth_epoch=%s "
            "AND (account_google_identity_id IS NOT NULL)=%s "
            "AND consumed_at IS NULL AND expires_at>clock_timestamp() RETURNING id,created_at,expires_at,account_google_identity_id,account_google_identity_revision",
            (
                challenge_id,
                session.user["id"],
                sid,
                secret,
                binding,
                operation,
                bound,
                session.auth_epoch,
                google,
            ),
        ).fetchone()
        if row is None:
            raise WorkspaceError("proof_invalid", 403)
        return ClaimedChallenge(
            str(row[0]),
            session.user["id"],
            sid,
            session.auth_epoch,
            operation,
            bound,
            row[1],
            row[2],
            str(row[3]) if row[3] else None,
            row[4],
        )
