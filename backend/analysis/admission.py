"""Shared PostgreSQL admission cannot be multiplied by sessions or web workers."""

import hashlib
from psycopg import Connection
from analysis import policy
from workspace.database import LOCK as WORKSPACE_LOCK, one
from workspace.errors import WorkspaceError


def lock(conn: Connection) -> None:
    # Every path first owns its user lock, then both global bookkeeping locks
    # in this order. Completion/deletion already need workspace byte accounting.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (WORKSPACE_LOCK,))
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (policy.LOCK,))


def reserve(conn: Connection, owner: str, dataset: str, provider: str) -> None:
    lock(conn)
    counts = conn.execute(
        "SELECT count(*),count(*) FILTER(WHERE user_id=%s) FROM app.analysis_jobs WHERE state='queued'",
        (owner,),
    ).fetchone()
    if counts[0] >= policy.QUEUED_GLOBAL or counts[1] >= policy.QUEUED_OWNER:
        raise WorkspaceError("analysis_busy", 429)
    scopes = [
        ("global", 120),
        ("account:" + owner, 12),
        ("dataset:" + hashlib.sha256(dataset.encode()).hexdigest(), 120),
        ("provider:" + provider, 60),
    ]
    conn.execute(
        "DELETE FROM app.analysis_admission WHERE expires_at<=clock_timestamp()"
    )
    count = conn.execute("SELECT count(*) FROM app.analysis_admission").fetchone()[0]
    missing = sum(
        conn.execute(
            "SELECT 1 FROM app.analysis_admission WHERE scope=%s", (scope,)
        ).fetchone()
        is None
        for scope, _ in scopes
    )
    if count + missing > 16384:
        raise WorkspaceError("capacity_reached", 429)
    for scope, maximum in scopes:
        current = one(
            conn,
            "SELECT units,expires_at,clock_timestamp() AS instant FROM app.analysis_admission WHERE scope=%s",
            (scope,),
        )
        if (
            current
            and current["expires_at"] > current["instant"]
            and current["units"] + 4 > maximum
        ):
            raise WorkspaceError("analysis_rate_limited", 429)
    # Reserve the complete four-call fallback/repair budget up front. Unused
    # attempts do not refund this minute's allowance and cannot fund a flood.
    for scope, _ in scopes:
        conn.execute(
            "INSERT INTO app.analysis_admission(scope,units,expires_at) VALUES(%s,4,clock_timestamp()+interval '1 minute') "
            "ON CONFLICT(scope) DO UPDATE SET units=CASE WHEN app.analysis_admission.expires_at<=clock_timestamp() THEN 4 ELSE app.analysis_admission.units+4 END,"
            "expires_at=CASE WHEN app.analysis_admission.expires_at<=clock_timestamp() THEN clock_timestamp()+interval '1 minute' ELSE app.analysis_admission.expires_at END",
            (scope,),
        )


def has_slot(conn: Connection, owner: str) -> bool:
    lock(conn)
    total, own = conn.execute(
        "SELECT count(*),count(*) FILTER(WHERE user_id=%s) FROM app.analysis_jobs WHERE physical_until>clock_timestamp()",
        (owner,),
    ).fetchone()
    return total < policy.RUNNING_GLOBAL and own < policy.RUNNING_OWNER


def observe(conn: Connection, owner: str, operation: str) -> None:
    """Polling cannot consume unlimited storage work or the separate cancel budget."""
    if operation not in {"read", "cancel"}:
        raise ValueError("analysis_observation_invalid")
    lock(conn)
    conn.execute(
        "DELETE FROM app.analysis_admission WHERE expires_at<=clock_timestamp()"
    )
    scopes = [operation + ":account:" + owner, operation + ":global"]
    cap = 120 if operation == "read" else 60
    total = conn.execute("SELECT count(*) FROM app.analysis_admission").fetchone()[0]
    missing = 0
    for scope in scopes:
        current = one(
            conn, "SELECT units FROM app.analysis_admission WHERE scope=%s", (scope,)
        )
        if current and current["units"] >= cap:
            raise WorkspaceError("analysis_rate_limited", 429)
        missing += current is None
    if total + missing > 16384:
        raise WorkspaceError("capacity_reached", 429)
    for scope in scopes:
        conn.execute(
            "INSERT INTO app.analysis_admission(scope,units,expires_at) VALUES(%s,1,clock_timestamp()+interval '1 minute') ON CONFLICT(scope) DO UPDATE SET units=app.analysis_admission.units+1",
            (scope,),
        )
