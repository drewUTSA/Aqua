"""Store only finite, replaceable lifecycle metadata, never model reasoning."""

from psycopg import Connection
from analysis.admission import lock
from analysis.policy import MAX_EVENTS, STAGES
from workspace.database import one, rows


def emit(conn: Connection, job: dict, stage: str, state: str | None = None) -> dict:
    if stage not in STAGES:
        raise ValueError("analysis_stage_invalid")
    lock(conn)
    state = state or job["state"]
    if stage == job["stage"] and state == job["state"]:
        return job
    conn.execute(
        "DELETE FROM app.analysis_events WHERE created_at<clock_timestamp()-interval '1 hour'"
    )
    # A full replay window degrades to snapshots, never unbounded accumulation.
    conn.execute(
        "DELETE FROM app.analysis_events WHERE (request_id,sequence) IN (SELECT request_id,sequence FROM app.analysis_events WHERE user_id=%s ORDER BY created_at DESC,request_id,sequence OFFSET 1023)",
        (job["user_id"],),
    )
    conn.execute(
        "DELETE FROM app.analysis_events WHERE (request_id,sequence) IN (SELECT request_id,sequence FROM app.analysis_events ORDER BY created_at DESC,request_id,sequence OFFSET 8191)"
    )
    sequence = min(MAX_EVENTS, job["last_event_sequence"] + 1)
    updated = one(
        conn,
        "UPDATE app.analysis_jobs SET stage=%s,state=%s,version=version+1,last_event_sequence=%s WHERE id=%s RETURNING *",
        (stage, state, sequence, job["id"]),
    )
    if job["last_event_sequence"] < MAX_EVENTS:
        conn.execute(
            "INSERT INTO app.analysis_events(user_id,request_id,sequence,version,state,stage) VALUES(%s,%s,%s,%s,%s,%s)",
            (job["user_id"], job["id"], sequence, updated["version"], state, stage),
        )
    if job["request_id"]:
        conn.execute(
            "UPDATE app.analysis_requests SET state=%s WHERE user_id=%s AND id=%s",
            (state, job["user_id"], job["request_id"]),
        )
    return updated


def public(job: dict) -> dict:
    return {
        "request_id": str(job["id"]),
        "sequence": job["last_event_sequence"],
        "version": job["version"],
        "state": job["state"],
        "stage": job["stage"],
    }


def after(conn: Connection, owner: str, request_id: str, sequence: int) -> list[dict]:
    return rows(
        conn,
        "SELECT request_id,sequence,version,state,stage FROM app.analysis_events WHERE user_id=%s AND request_id=%s AND sequence>%s ORDER BY sequence LIMIT 32",
        (owner, request_id, sequence),
    )
