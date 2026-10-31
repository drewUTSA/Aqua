"""Epoch fences invalidate history while writes inspect only the bounded live set."""

from psycopg import Connection

from account.policy import MAX_SESSIONS
from workspace.errors import WorkspaceError


def revoke_all(conn: Connection, owner: str, epoch: int) -> None:
    """Caller owns the user lock. Never update retained expired session history."""
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    rows = conn.execute(
        "SELECT id FROM app.sessions WHERE user_id=%s AND auth_epoch=%s "
        "AND revoked_at IS NULL AND idle_expires_at>%s LIMIT %s",
        (owner, epoch, instant, MAX_SESSIONS + 1),
    ).fetchall()
    if len(rows) > MAX_SESSIONS:
        raise WorkspaceError("service_unavailable", 503)
    # New logins/reset/method changes share the user lock. No new old-epoch
    # session can appear between this bounded read and the exact-ID update.
    conn.execute(
        "UPDATE app.users SET auth_epoch=auth_epoch+1,updated_at=clock_timestamp() WHERE id=%s AND auth_epoch=%s",
        (owner, epoch),
    )
    if rows:
        conn.execute(
            "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s AND auth_epoch=%s AND id=ANY(%s)",
            (owner, epoch, [row[0] for row in rows]),
        )
