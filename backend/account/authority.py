"""One current owner/session and exact target authority for account actions."""

from psycopg import Connection

from auth.config import AuthPolicy
from auth.security import UserSession
from workspace.database import guard
from workspace.errors import WorkspaceError


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
