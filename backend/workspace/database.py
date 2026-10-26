"""Short transactions recheck authority and account/global resource bounds."""

from psycopg import Connection
from auth.security import UserSession
from auth.config import AuthPolicy

from psycopg.rows import dict_row

from auth.accounts import grant_state
from workspace.errors import WorkspaceError

LOCK = 1095848262


def rows(conn: Connection, statement: str, values: tuple = ()) -> list[dict]:
    with conn.cursor(row_factory=dict_row) as cursor:
        return cursor.execute(statement, values).fetchall()


def one(conn: Connection, statement: str, values: tuple = ()) -> dict | None:
    result = rows(conn, statement, values)
    return result[0] if result else None


def public(row: dict) -> dict:
    return {
        key: (
            str(value)
            if key
            in {
                "id",
                "project_id",
                "chat_id",
                "request_id",
                "reply_to",
                "input_message_id",
                "reply_message_id",
                "client_request_id",
            }
            and value is not None
            else value
        )
        for key, value in row.items()
        if key
        not in {
            "user_id",
            "fingerprint",
            "deleted_at",
            "next_message_sequence",
            "dataset_key",
            "grant_version",
            "retry_of",
        }
    }


def guard(
    conn: Connection,
    session: UserSession,
    policy: AuthPolicy,
    *,
    mutate: bool = False,
    data: bool = False,
) -> None:
    # A second check inside the data transaction closes dependency-to-write races.
    # All workspace paths take user, session, then grant locks in that order.
    # A concurrent reset/logout cannot revoke authority between this check and
    # the short history/result transaction. No lock spans provider work.
    state = conn.execute(
        "SELECT status,auth_epoch FROM app.users WHERE id=%s FOR UPDATE",
        (session.user["id"],),
    ).fetchone()
    if state is None or state != ("active", session.auth_epoch):
        raise WorkspaceError("session_invalid", 401)
    valid = conn.execute(
        "SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s AND revoked_at IS NULL AND auth_epoch=%s AND idle_expires_at>clock_timestamp() AND absolute_expires_at>clock_timestamp() FOR SHARE",
        (session.user["id"], session.token_digest, session.auth_epoch),
    ).fetchone()
    if valid is None:
        raise WorkspaceError("session_invalid", 401)
    if data:
        conn.execute(
            "SELECT user_id FROM app.dataset_grants WHERE user_id=%s AND dataset_key=%s FOR SHARE",
            (session.user["id"], policy.dataset_key),
        )
        if not grant_state(conn, session.user["id"], policy)[0]:
            raise WorkspaceError("access_denied", 403)


def admit(conn: Connection, owner: str) -> None:
    """One durable per-account budget covers cookies, workers and failed writes.

    It is committed separately from item work so rejected IDs/revisions cannot
    roll back the budget. P07 supplies full analytical job admission separately.
    """
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    old = one(
        conn,
        "SELECT hits,expires_at,clock_timestamp() AS instant FROM app.workspace_admission WHERE user_id=%s",
        (owner,),
    )
    if old and old["expires_at"] > old["instant"] and old["hits"] >= 60:
        raise WorkspaceError("rate_limited", 429)
    conn.execute(
        "INSERT INTO app.workspace_admission(user_id,hits,expires_at) VALUES(%s,1,clock_timestamp()+interval '1 minute') "
        "ON CONFLICT(user_id) DO UPDATE SET hits=CASE WHEN app.workspace_admission.expires_at<=clock_timestamp() THEN 1 ELSE app.workspace_admission.hits+1 END, "
        "expires_at=CASE WHEN app.workspace_admission.expires_at<=clock_timestamp() THEN clock_timestamp()+interval '1 minute' ELSE app.workspace_admission.expires_at END",
        (owner,),
    )


def allocate(conn: Connection, owner: str, size: int) -> None:
    # Global accounting lock is held only for bounded bookkeeping, never a model.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    conn.execute(
        "INSERT INTO app.workspace_usage(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
        (owner,),
    )
    current = conn.execute(
        "SELECT content_bytes FROM app.workspace_usage WHERE user_id=%s", (owner,)
    ).fetchone()[0]
    total = conn.execute(
        "SELECT content_bytes FROM app.workspace_totals WHERE singleton"
    ).fetchone()[0]
    target = max(0, current + size)
    delta = target - current
    if target > 16777216 or total + delta > 209715200:
        raise WorkspaceError("capacity_reached", 429)
    conn.execute(
        "UPDATE app.workspace_usage SET content_bytes=%s WHERE user_id=%s",
        (target, owner),
    )
    conn.execute(
        "UPDATE app.workspace_totals SET content_bytes=content_bytes+%s WHERE singleton",
        (delta,),
    )


def bounded_count(
    conn: Connection, table: str, owner: str, cap: int, *, active: bool = False
) -> None:
    if table not in {
        "projects",
        "chats",
        "saved_prompts",
        "analysis_requests",
        "saved_prompt_uses",
    }:
        raise ValueError("workspace_table_invalid")
    predicate = (
        " AND deleted_at IS NULL"
        if active and table in {"chats", "projects", "saved_prompts"}
        else ""
    )
    count = conn.execute(
        f"SELECT count(*) FROM app.{table} WHERE user_id=%s{predicate}", (owner,)
    ).fetchone()[0]
    if count >= cap:
        raise WorkspaceError("capacity_reached", 429)
