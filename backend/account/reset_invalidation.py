"""Retire only the bounded currently valid reset links, preserving history."""

from psycopg import Connection

from workspace.errors import WorkspaceError

# The established recipient budget admits at most three links per 24 hours;
# reset links live at most thirty minutes. Excess indicates unexpected state.
MAX_LIVE_RESETS = 3
LIVE_RESETS_SQL = (
    "SELECT id FROM app.auth_challenges WHERE purpose='password_reset' "
    "AND target_email_key=%s AND expires_at>%s AND consumed_at IS NULL "
    "AND user_id=%s AND password_auth_epoch=%s LIMIT %s FOR UPDATE"
)


def invalidate_resets(conn: Connection, owner: str, epoch: int, email: str) -> None:
    """Caller owns mail admission and user locks; old epochs already deny."""
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    tickets = conn.execute(
        LIVE_RESETS_SQL, (email, instant, owner, epoch, MAX_LIVE_RESETS + 1)
    ).fetchall()
    if len(tickets) > MAX_LIVE_RESETS:
        raise WorkspaceError("security_unavailable", 503)
    if not tickets:
        return
    ids = [row[0] for row in tickets]
    jobs = conn.execute(
        "SELECT id FROM app.account_mail WHERE challenge_id=ANY(%s) AND purpose='reset_password' LIMIT %s FOR UPDATE",
        (ids, MAX_LIVE_RESETS + 1),
    ).fetchall()
    if len(jobs) > MAX_LIVE_RESETS:
        raise WorkspaceError("security_unavailable", 503)
    conn.execute(
        "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() WHERE id=ANY(%s)",
        (ids,),
    )
    if jobs:
        conn.execute(
            "DELETE FROM app.account_mail WHERE id=ANY(%s)", ([row[0] for row in jobs],)
        )
