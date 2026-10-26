"""Atomically reserve canonical input/request/reply IDs and stable sequences."""

from psycopg import Connection
from auth.security import UserSession
from pydantic import BaseModel

from uuid import uuid4
from workspace.cursors import fingerprint
from workspace.database import allocate, bounded_count, one
from workspace.errors import WorkspaceError
from workspace.history import chat_row, project_exists


def begin(
    conn: Connection,
    session: UserSession,
    body: BaseModel,
    *,
    chat_id: str | None,
    input_id: str | None,
    default_model: str,
) -> tuple[str, bool]:
    owner = session.user["id"]
    question = getattr(body, "question", None)
    model = getattr(body, "model", None)
    project = getattr(body, "project_id", None)
    digest = fingerprint(
        {
            "chat_id": chat_id,
            "input_id": input_id,
            "question": question,
            "model": model,
            "project_id": project,
        }
    )
    existing = one(
        conn,
        "SELECT id,fingerprint,chat_id FROM app.analysis_requests WHERE user_id=%s AND client_request_id=%s",
        (owner, body.client_request_id),
    )
    if existing:
        chat_row(conn, owner, str(existing["chat_id"]))
        if bytes(existing["fingerprint"]) != digest:
            raise WorkspaceError("idempotency_conflict", 409)
        return str(existing["id"]), False
    retry_of = None
    if input_id:
        original = one(
            conn,
            "SELECT m.content,r.id,r.state,r.requested_model,v.response FROM app.messages m "
            "JOIN app.analysis_requests r ON r.user_id=m.user_id AND r.chat_id=m.chat_id AND r.id=m.request_id "
            "LEFT JOIN app.visual_results v ON v.user_id=r.user_id AND v.chat_id=r.chat_id AND v.request_id=r.id "
            "WHERE m.user_id=%s AND m.chat_id=%s AND m.id=%s AND m.role='user'",
            (owner, chat_id, input_id),
        )
        if original is None:
            raise WorkspaceError("not_found")
        if original["state"] != "interrupted" and (
            original["state"] != "error"
            or not original.get("response", {}).get("error", {}).get("retryable")
        ):
            raise WorkspaceError("retry_unavailable", 409)
        question, model, retry_of = (
            original["content"],
            original["requested_model"],
            original["id"],
        )
    if len(question.encode()) > 8000:
        raise WorkspaceError("invalid_request", 422)
    allocate(conn, owner, 1024 + (0 if input_id else len(question.encode())))
    bounded_count(conn, "analysis_requests", owner, 10000)
    if (
        conn.execute("SELECT count(*) FROM app.analysis_requests").fetchone()[0]
        >= 100000
    ):
        raise WorkspaceError("capacity_reached", 429)
    if chat_id is None:
        project_exists(conn, owner, str(project) if project else None)
        bounded_count(conn, "chats", owner, 100, active=True)
        bounded_count(conn, "chats", owner, 1000)
        if conn.execute("SELECT count(*) FROM app.chats").fetchone()[0] >= 10000:
            raise WorkspaceError("capacity_reached", 429)
        chat_id = str(uuid4())
        title = " ".join(question.split())[:120]
        allocate(conn, owner, len(title.encode()))
        conn.execute(
            "INSERT INTO app.chats(id,user_id,project_id,title) VALUES(%s,%s,%s,%s)",
            (chat_id, owner, project, title),
        )
    chat = chat_row(conn, owner, chat_id, lock=True)
    if chat["archived"]:
        raise WorkspaceError("chat_archived", 409)
    needed = 1 if input_id else 2
    if chat["message_count"] + needed > 200:
        raise WorkspaceError("capacity_reached", 429)
    request_id, reply_id = str(uuid4()), str(uuid4())
    sequence = chat["next_message_sequence"]
    if input_id is None:
        input_id = str(uuid4())
        conn.execute(
            "INSERT INTO app.messages(id,user_id,chat_id,sequence,role,content,request_id,model_id,status) VALUES(%s,%s,%s,%s,'user',%s,%s,%s,'complete')",
            (
                input_id,
                owner,
                chat_id,
                sequence,
                question,
                request_id,
                model or default_model,
            ),
        )
        sequence += 1
    conn.execute(
        "INSERT INTO app.messages(id,user_id,chat_id,sequence,role,request_id,reply_to,model_id,status) VALUES(%s,%s,%s,%s,'aqua',%s,%s,%s,'pending')",
        (
            reply_id,
            owner,
            chat_id,
            sequence,
            request_id,
            input_id,
            model or default_model,
        ),
    )
    conn.execute(
        "INSERT INTO app.analysis_requests(id,user_id,chat_id,client_request_id,fingerprint,input_message_id,reply_message_id,retry_of,state,requested_model,dataset_key,grant_version) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s)",
        (
            request_id,
            owner,
            chat_id,
            body.client_request_id,
            digest,
            input_id,
            reply_id,
            retry_of,
            model or default_model,
            session.dataset_key,
            session.grant_version,
        ),
    )
    conn.execute(
        "UPDATE app.chats SET next_message_sequence=next_message_sequence+%s,message_count=message_count+%s,last_activity_at=clock_timestamp(),revision=revision+1 WHERE user_id=%s AND id=%s",
        (needed, needed, owner, chat_id),
    )
    return request_id, True
