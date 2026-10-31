"""Reusable bounded proof checks; consumption belongs to the mutation transaction."""

from psycopg import Connection

from account.authority import current_id, owned_target
from account.policy import digest, target_digest
from auth.config import AuthPolicy
from auth.security import UserSession
from workspace.errors import WorkspaceError

# Shared by cheap detached-work admission and the final locked consumption.
# Public inputs are parameters, never SQL fragments or caller-chosen digests.
BINDINGS = (
    "p.user_id=%s AND p.session_id=%s AND p.auth_epoch=%s "
    "AND p.operation=%s AND p.target_digest=%s AND p.secret_digest=%s "
    "AND p.consumed_at IS NULL AND p.expires_at>clock_timestamp() "
    "AND c.id=p.challenge_id AND c.user_id=p.user_id AND c.session_id=p.session_id "
    "AND c.purpose='reauth' AND c.account_operation=p.operation "
    "AND c.account_target_digest=p.target_digest AND c.account_auth_epoch=p.auth_epoch "
    "AND c.consumed_at IS NOT NULL AND c.expires_at>clock_timestamp() "
    # Schema6 has no external-identity revision snapshot. Until P10c adds it
    # and a real Google verifier, even this low-level primitive rejects Google
    # proofs; active-again tombstones cannot revive synthetic/legacy authority.
    "AND p.method='password' AND EXISTS(SELECT 1 FROM app.password_credentials k "
    "WHERE k.user_id=p.user_id AND k.changed_at=p.password_changed_at)"
)


def check_proof(
    conn: Connection,
    policy: AuthPolicy,
    session: UserSession,
    operation: str,
    target: object,
    secret: bytes,
    *,
    lock: bool = False,
    method: str | None = None,
) -> tuple:
    """A non-consuming precheck never authorizes the later mutation by itself."""
    values = (
        session.user["id"],
        current_id(conn, session, policy),
        session.auth_epoch,
        operation,
        target_digest(operation, target),
        digest(secret),
    )
    owned_target(conn, session, operation, target)
    row = conn.execute(
        "SELECT p.id,p.method FROM app.account_action_proofs p "
        "JOIN app.auth_challenges c ON c.id=p.challenge_id WHERE "
        + BINDINGS
        + (" FOR UPDATE OF c" if lock else ""),
        values,
    ).fetchone()
    if row is None or method is not None and row[1] != method:
        raise WorkspaceError("proof_invalid", 403)
    return values


def consume_proof(
    conn: Connection,
    policy: AuthPolicy,
    session: UserSession,
    operation: str,
    target: object,
    secret: bytes,
    *,
    method: str | None = None,
) -> None:
    """Lock user/session, then challenge before proof, matching cascade cleanup.

    A later failed mutation rolls back this consumption too. The conditional
    update checks expiry again; a timer expiring after the precheck cannot win.
    """
    values = check_proof(
        conn, policy, session, operation, target, secret, lock=True, method=method
    )
    row = conn.execute(
        "UPDATE app.account_action_proofs p SET consumed_at=clock_timestamp() "
        "FROM app.auth_challenges c WHERE " + BINDINGS + " RETURNING p.id",
        values,
    ).fetchone()
    if row is None:
        raise WorkspaceError("proof_invalid", 403)
