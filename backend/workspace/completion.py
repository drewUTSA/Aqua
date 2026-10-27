"""Fence synchronous completion; transport replay never repeats model work."""

from psycopg import Connection
from auth.security import UserSession
from collections.abc import Callable
from nl2sql.config import Settings

import json

from fastapi.responses import JSONResponse
from psycopg.types.json import Jsonb

from nl2sql.response import outage_response
from workspace.database import allocate, one, public, rows
from workspace.errors import WorkspaceError
from workspace.history import MESSAGE, chat_row, message_public


def snapshot(
    conn: Connection, owner: str, request_id: str, session: UserSession
) -> dict:
    request = one(
        conn,
        "SELECT id,client_request_id,state,input_message_id,reply_message_id,chat_id FROM app.analysis_requests WHERE user_id=%s AND id=%s",
        (owner, request_id),
    )
    if request is None:
        raise WorkspaceError("not_found")
    chat = chat_row(conn, owner, str(request["chat_id"]))
    messages = rows(
        conn,
        f"SELECT {MESSAGE},r.dataset_key,v.response FROM app.messages m "
        "JOIN app.analysis_requests r ON r.user_id=m.user_id AND r.chat_id=m.chat_id AND r.id=m.request_id "
        "LEFT JOIN app.visual_results v ON v.user_id=r.user_id AND v.chat_id=r.chat_id AND v.request_id=r.id "
        "WHERE m.user_id=%s AND m.chat_id=%s AND m.id IN(%s,%s)",
        (
            owner,
            request["chat_id"],
            request["input_message_id"],
            request["reply_message_id"],
        ),
    )
    by_id = {str(item["id"]): message_public(item, session) for item in messages}
    assistant = by_id[str(request["reply_message_id"])]
    return {
        "chat": public(chat),
        "request": public(request),
        "input_message": by_id[str(request["input_message_id"])],
        "assistant_message": assistant,
        "response": assistant["response"],
    }


def execute(
    runner: Callable,
    question: str,
    model: str,
    session: UserSession,
    settings: Settings,
) -> dict:
    result = runner(question, model, session, settings)
    if isinstance(result, JSONResponse):
        result = json.loads(result.body)
    if (
        not isinstance(result, dict)
        or result.get("status") not in {"success", "error"}
        or not isinstance(result.get("message"), str)
        or not all(
            isinstance(result.get(key), list)
            for key in ("tables", "visualizations", "kpis")
        )
    ):
        return outage_response(
            "result_invalid", "The result could not be saved safely."
        )
    try:
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError):
        return outage_response(
            "result_invalid", "The result could not be saved safely."
        )
    # jsonb adds spaces; a margin keeps the database's independent hard check.
    if len(encoded.encode()) > 240000:
        return outage_response(
            "result_too_large",
            "The result is too large to save. Ask for a smaller result.",
        )
    return result


def finish(
    conn: Connection,
    session: UserSession,
    request_id: str,
    response: dict,
    *,
    expected_states: tuple[str, ...] = ("pending",),
) -> None:
    owner = session.user["id"]
    request = one(
        conn,
        "SELECT chat_id,reply_message_id,state,reserved_bytes FROM app.analysis_requests WHERE user_id=%s AND id=%s FOR UPDATE",
        (owner, request_id),
    )
    chat_row(conn, owner, str(request["chat_id"]), lock=True)
    if request["state"] not in expected_states:
        return
    size = conn.execute(
        "SELECT octet_length(%s::jsonb::text)", (Jsonb(response),)
    ).fetchone()[0]
    try:
        allocate(conn, owner, size - request["reserved_bytes"])
    except WorkspaceError as error:
        if error.code != "capacity_reached":
            raise
        response = outage_response(
            "workspace_capacity",
            "The workspace cannot save this result. Remove older chats and try again.",
        )
        size = conn.execute(
            "SELECT octet_length(%s::jsonb::text)", (Jsonb(response),)
        ).fetchone()[0]
        allocate(conn, owner, size - request["reserved_bytes"])
    state = "complete" if response["status"] == "success" else "error"
    conn.execute(
        "INSERT INTO app.visual_results(user_id,chat_id,request_id,response) VALUES(%s,%s,%s,%s)",
        (owner, request["chat_id"], request_id, Jsonb(response)),
    )
    conn.execute(
        "UPDATE app.analysis_requests SET state=%s,reserved_bytes=0,finished_at=clock_timestamp() WHERE user_id=%s AND id=%s AND state=ANY(%s)",
        (state, owner, request_id, list(expected_states)),
    )
    conn.execute(
        "UPDATE app.messages SET status=%s WHERE user_id=%s AND chat_id=%s AND id=%s AND request_id=%s",
        (state, owner, request["chat_id"], request["reply_message_id"], request_id),
    )


def interrupt(conn: Connection, owner: str, request_id: str | None = None) -> None:
    """Retire abandoned records, fencing any late completion without rerunning it."""
    conn.execute("SELECT id FROM app.users WHERE id=%s FOR UPDATE", (owner,))
    pending = rows(
        conn,
        "SELECT id,chat_id,reply_message_id,reserved_bytes FROM app.analysis_requests WHERE user_id=%s AND state='pending' "
        + (
            "AND id=%s"
            if request_id
            else "AND created_at<clock_timestamp()-interval '2 hours'"
        )
        + " FOR UPDATE",
        (owner, request_id) if request_id else (owner,),
    )
    if not pending:
        return
    allocate(conn, owner, -sum(item["reserved_bytes"] for item in pending))
    for item in pending:
        conn.execute(
            "UPDATE app.analysis_requests SET state='interrupted',reserved_bytes=0,finished_at=clock_timestamp() WHERE user_id=%s AND id=%s AND state='pending'",
            (owner, item["id"]),
        )
        conn.execute(
            "UPDATE app.messages SET status='interrupted' WHERE user_id=%s AND chat_id=%s AND id=%s AND request_id=%s",
            (owner, item["chat_id"], item["reply_message_id"], item["id"]),
        )
