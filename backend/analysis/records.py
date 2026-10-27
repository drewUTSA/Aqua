"""Canonical jobs link private history without leaking worker/session metadata."""

from dataclasses import replace
from psycopg import Connection
from psycopg.types.json import Jsonb
from auth.accounts import grant_state
from auth.security import UserSession
from auth.config import AuthPolicy
from analysis.policy import TERMINAL
from workspace import completion
from workspace.database import allocate, guard, one
from workspace.errors import WorkspaceError
from workspace.history import chat_row


def identity(job: dict) -> UserSession:
    return UserSession(
        {"id": str(job["user_id"])},
        "",
        bytes(job["session_digest"]),
        True,
        job["grant_version"],
        job["auth_epoch"],
        job["dataset_key"],
    )


def authorize(
    conn: Connection, session: UserSession, policy: AuthPolicy, job: dict | None = None
) -> UserSession:
    guard(conn, session, policy, data=True)
    allowed, version = grant_state(conn, session.user["id"], policy)
    if not allowed or (
        job
        and (
            job["dataset_key"] != policy.dataset_key or job["grant_version"] != version
        )
    ):
        raise WorkspaceError("access_denied", 403)
    if job and job["request_id"]:
        row = one(
            conn,
            "SELECT chat_id FROM app.analysis_requests WHERE user_id=%s AND id=%s",
            (session.user["id"], job["request_id"]),
        )
        chat_row(conn, session.user["id"], str(row["chat_id"]))
    return replace(
        session, can_query=True, grant_version=version, dataset_key=policy.dataset_key
    )


def get(conn: Connection, owner: str, request_id: str, *, lock: bool = False) -> dict:
    job = one(
        conn,
        "SELECT * FROM app.analysis_jobs WHERE user_id=%s AND id=%s"
        + (" FOR UPDATE" if lock else ""),
        (owner, request_id),
    )
    if job is None:
        raise WorkspaceError("not_found")
    return job


def snapshot(conn: Connection, session: UserSession, request_id: str) -> dict:
    saved = completion.snapshot(conn, session.user["id"], request_id, session)
    job = one(
        conn,
        "SELECT * FROM app.analysis_jobs WHERE user_id=%s AND id=%s",
        (session.user["id"], request_id),
    )
    saved["request"].update(
        stage=job["stage"] if job else saved["request"]["state"],
        version=job["version"] if job else 1,
        last_event_sequence=job["last_event_sequence"] if job else 0,
        deadline_at=job["deadline_at"] if job else None,
        cancel_requested=job["cancel_requested"] if job else False,
        cancellable=bool(job and job["state"] not in TERMINAL),
    )
    return saved


def insert(
    conn: Connection,
    session: UserSession,
    job_id: str,
    question: str,
    model: str,
    context: list[dict],
    digest: bytes,
    *,
    request_id: str | None,
) -> dict:
    size = (
        len(question.encode())
        + conn.execute(
            "SELECT octet_length(%s::jsonb::text)", (Jsonb(context),)
        ).fetchone()[0]
    )
    allocate(conn, session.user["id"], size)
    conn.execute(
        "INSERT INTO app.analysis_jobs(id,user_id,request_id,session_digest,auth_epoch,dataset_key,grant_version,question,model,context,context_digest,content_bytes,state,stage,deadline_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'queued','queued',statement_timestamp()+interval '120 seconds')",
        (
            job_id,
            session.user["id"],
            request_id,
            session.token_digest,
            session.auth_epoch,
            session.dataset_key,
            session.grant_version,
            question,
            model,
            Jsonb(context),
            digest,
            size,
        ),
    )
    if request_id:
        conn.execute(
            "UPDATE app.analysis_requests SET state='queued' WHERE user_id=%s AND id=%s",
            (session.user["id"], request_id),
        )
    return get(conn, session.user["id"], job_id)


def purge_input(conn: Connection, job: dict) -> None:
    if job["content_bytes"]:
        allocate(conn, str(job["user_id"]), -job["content_bytes"])
    conn.execute(
        "UPDATE app.analysis_jobs SET question='',context='[]',content_bytes=0 WHERE id=%s",
        (job["id"],),
    )
