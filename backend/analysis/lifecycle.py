"""Short fenced commits release reservations once and never resurrect deleted data."""

from psycopg import Connection
from psycopg.types.json import Jsonb
from analysis import events, records
from analysis.policy import TERMINAL
from workspace import completion
from workspace.database import allocate, one
from nl2sql.response import outage_response
from auth.security import UserSession


class CommitFence(RuntimeError):
    def __init__(self, state: str) -> None:
        self.state = state


def terminate(
    conn: Connection,
    job: dict,
    state: str,
    *,
    reaped: bool = False,
    quarantine: bool = False,
    remote_uncertain: bool = False,
) -> dict:
    if state not in TERMINAL:
        raise ValueError("analysis_terminal_invalid")
    if job["state"] not in TERMINAL:
        records.purge_input(conn, job)
        if job["request_id"]:
            request = one(
                conn,
                "SELECT reserved_bytes,chat_id,reply_message_id FROM app.analysis_requests WHERE user_id=%s AND id=%s FOR UPDATE",
                (job["user_id"], job["request_id"]),
            )
            allocate(conn, str(job["user_id"]), -request["reserved_bytes"])
            conn.execute(
                "UPDATE app.analysis_requests SET reserved_bytes=0,state=%s,finished_at=clock_timestamp() WHERE user_id=%s AND id=%s",
                (state, job["user_id"], job["request_id"]),
            )
            conn.execute(
                "UPDATE app.messages SET status=%s WHERE user_id=%s AND chat_id=%s AND id=%s",
                (
                    state,
                    job["user_id"],
                    request["chat_id"],
                    request["reply_message_id"],
                ),
            )
        job = events.emit(conn, job, state, state)
        conn.execute(
            "UPDATE app.analysis_jobs SET finished_at=clock_timestamp(),lease_until=NULL,lease_token=lease_token+1 WHERE id=%s",
            (job["id"],),
        )
    if reaped or job["started_at"] is None:
        conn.execute(
            "UPDATE app.analysis_jobs SET physical_until=NULL WHERE id=%s", (job["id"],)
        )
    elif quarantine:
        conn.execute(
            "UPDATE app.analysis_jobs SET physical_until='9999-01-01T00:00:00Z' WHERE id=%s",
            (job["id"],),
        )
    elif remote_uncertain:
        conn.execute(
            "UPDATE app.analysis_jobs SET physical_until=greatest(physical_until,clock_timestamp()+interval '10 seconds') WHERE id=%s",
            (job["id"],),
        )
    return records.get(conn, str(job["user_id"]), str(job["id"]))


def complete(
    conn: Connection, job: dict, session: UserSession, response: dict, status: int
) -> dict:
    records.purge_input(conn, job)
    if job["request_id"]:
        completion.finish(
            conn,
            session,
            str(job["request_id"]),
            response,
            expected_states=("running",),
        )
        request = one(
            conn,
            "SELECT state FROM app.analysis_requests WHERE user_id=%s AND id=%s",
            (job["user_id"], job["request_id"]),
        )
        state = request["state"]
    else:
        size = conn.execute(
            "SELECT octet_length(%s::jsonb::text)", (Jsonb(response),)
        ).fetchone()[0]
        allocate(conn, str(job["user_id"]), size)
        conn.execute(
            "UPDATE app.analysis_jobs SET response=%s,http_status=%s,content_bytes=%s WHERE id=%s",
            (Jsonb(response), status, size, job["id"]),
        )
        state = "complete" if response["status"] == "success" else "error"
    job = events.emit(conn, job, state, state)
    accepted = conn.execute(
        "UPDATE app.analysis_jobs SET finished_at=clock_timestamp(),lease_until=NULL,physical_until=NULL WHERE id=%s AND lease_token=%s AND lease_owner=%s AND deadline_at>clock_timestamp() AND lease_until>clock_timestamp() RETURNING id",
        (job["id"], job["lease_token"], job["lease_owner"]),
    ).fetchone()
    if accepted is None:
        expired = conn.execute(
            "SELECT %s<=clock_timestamp()", (job["deadline_at"],)
        ).fetchone()[0]
        raise CommitFence("expired" if expired else "interrupted")
    return records.get(conn, str(job["user_id"]), str(job["id"]))


def deleted(conn: Connection, owner: str, chat_id: str) -> None:
    jobs = conn.execute(
        "SELECT j.id FROM app.analysis_jobs j JOIN app.analysis_requests r ON r.user_id=j.user_id AND r.id=j.request_id WHERE j.user_id=%s AND r.chat_id=%s",
        (owner, chat_id),
    ).fetchall()
    for (job_id,) in jobs:
        job = records.get(conn, owner, str(job_id), lock=True)
        if job["state"] not in TERMINAL:
            terminate(conn, job, "interrupted")
        else:
            records.purge_input(conn, job)
        conn.execute(
            "UPDATE app.analysis_jobs SET context_digest=decode(repeat('00',32),'hex'),cancel_requested=true WHERE id=%s",
            (job_id,),
        )


def unavailable(state: str) -> tuple[dict, int]:
    messages = {
        "cancelled": "The request was cancelled.",
        "expired": "The request reached its time limit.",
        "interrupted": "The request was interrupted. You can retry it.",
    }
    return (
        outage_response(
            "analysis_" + state, messages.get(state, "The analysis could not finish.")
        ),
        503,
    )
