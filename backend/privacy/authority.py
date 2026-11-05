"""Current session, epoch and result grants fence every new private delivery."""

from auth.accounts import grant_state
from auth.security import UserSession
from workspace.database import guard
from workspace.errors import WorkspaceError


def job_session(conn, job):
    row = conn.execute(
        "SELECT token_digest FROM app.sessions WHERE user_id=%s AND id=%s",
        (job["user_id"], job["session_id"]),
    ).fetchone()
    if row is None:
        raise WorkspaceError("session_invalid", 401)
    return UserSession(
        {"id": str(job["user_id"])},
        "",
        bytes(row[0]),
        False,
        job["grant_version"],
        job["auth_epoch"],
        job["dataset_key"],
    )


def check(conn, job, policy, session=None, *, results=True, lock=True):
    current = session or job_session(conn, job)
    if (
        str(job["user_id"]) != current.user["id"]
        or job["auth_epoch"] != current.auth_epoch
    ):
        raise WorkspaceError("not_found")
    if lock:
        guard(conn, current, policy)
    row = conn.execute(
        "SELECT u.status,u.auth_epoch,u.privacy_epoch,s.id,s.auth_epoch,s.revoked_at IS NULL AND s.idle_expires_at>clock_timestamp() AND s.absolute_expires_at>clock_timestamp() FROM app.users u JOIN app.sessions s ON s.user_id=u.id WHERE u.id=%s AND s.id=%s AND s.token_digest=%s",
        (current.user["id"], job["session_id"], current.token_digest),
    ).fetchone()
    if (
        row is None
        or row[:3] != ("active", job["auth_epoch"], job["privacy_epoch"])
        or row[4] != job["auth_epoch"]
        or row[5] is not True
    ):
        raise WorkspaceError("not_found")
    allowed, version = grant_state(conn, current.user["id"], policy)
    if (
        results
        and job["contains_results"]
        and (
            not allowed
            or policy.dataset_key != job["dataset_key"]
            or version != job["grant_version"]
        )
    ):
        raise WorkspaceError("not_found")
    return current, bool(allowed), version


def privacy_epoch(conn, owner):
    return conn.execute(
        "SELECT privacy_epoch FROM app.users WHERE id=%s", (owner,)
    ).fetchone()[0]
