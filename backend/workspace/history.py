"""Indexed owner-scoped recents/title search and bounded historical delivery."""

from psycopg import Connection
from auth.security import UserSession
from auth.config import AuthPolicy
from pydantic import BaseModel

from workspace.cursors import Cursors
from workspace.database import allocate, one, public, rows
from workspace.errors import WorkspaceError

CHAT = "id,title,project_id,archived,revision,message_count,last_activity_at,created_at"
MESSAGE = "m.id,m.chat_id,m.sequence,m.role,m.content,m.request_id,m.reply_to,m.model_id,m.status,m.created_at"


def chat_row(conn: Connection, owner: str, chat_id: str, *, lock: bool = False) -> dict:
    item = one(
        conn,
        f"SELECT {CHAT},next_message_sequence FROM app.chats WHERE user_id=%s AND id=%s AND deleted_at IS NULL"
        + (" FOR UPDATE" if lock else ""),
        (owner, chat_id),
    )
    if item is None:
        raise WorkspaceError("not_found")
    return item


def project_exists(conn: Connection, owner: str, project_id: str | None) -> None:
    if (
        project_id is not None
        and one(
            conn,
            "SELECT id FROM app.projects WHERE user_id=%s AND id=%s AND NOT archived AND deleted_at IS NULL",
            (owner, project_id),
        )
        is None
    ):
        raise WorkspaceError("not_found")


def list_chats(
    conn: Connection,
    session: UserSession,
    secret: str,
    *,
    limit: int,
    cursor: str | None,
    search: str,
    archived: bool,
    project_id: str | None,
) -> dict:
    owner = session.user["id"]
    token = Cursors(
        secret,
        owner,
        {
            "kind": "chats",
            "search": search,
            "archived": archived,
            "project_id": project_id,
        },
    )
    position = token.decode(cursor)
    project_exists(conn, owner, project_id)
    predicates = ["user_id=%s", "deleted_at IS NULL", "archived=%s"]
    values = [owner, archived]
    if project_id:
        predicates.append("project_id=%s")
        values.append(project_id)
    if search:
        # Prefix search uses the owner/lower(title) pattern index. Wildcards are
        # literal user text, never an accidental all-message search.
        escaped = (
            search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        )
        predicates.append("lower(title) LIKE %s ESCAPE E'\\\\'")
        values.append(escaped + "%")
    if position:
        predicates.append("(last_activity_at,id)<(%s::timestamptz,%s::uuid)")
        values.extend(position)
    values.append(limit + 1)
    found = rows(
        conn,
        f"SELECT {CHAT} FROM app.chats WHERE "
        + " AND ".join(predicates)
        + " ORDER BY last_activity_at DESC,id DESC LIMIT %s",
        tuple(values),
    )
    page = found[:limit]
    following = (
        token.encode([page[-1]["last_activity_at"], str(page[-1]["id"])])
        if len(found) > limit
        else None
    )
    return {"items": [public(item) for item in page], "next_cursor": following}


def message_rows(
    conn: Connection,
    owner: str,
    chat_id: str,
    session: UserSession,
    policy: AuthPolicy,
    *,
    limit: int,
    cursor: str | None,
    secret: str,
) -> dict:
    chat_row(conn, owner, chat_id)
    token = Cursors(secret, owner, {"kind": "messages", "chat_id": chat_id})
    position = token.decode(cursor, messages=True)
    found = rows(
        conn,
        f"SELECT {MESSAGE},r.dataset_key,v.response FROM app.messages m "
        "LEFT JOIN app.analysis_requests r ON r.user_id=m.user_id AND r.chat_id=m.chat_id AND r.id=m.request_id "
        "LEFT JOIN app.visual_results v ON v.user_id=r.user_id AND v.chat_id=r.chat_id AND v.request_id=r.id "
        "WHERE m.user_id=%s AND m.chat_id=%s"
        + (" AND m.sequence<%s" if position else "")
        + " ORDER BY m.sequence DESC LIMIT %s",
        (owner, chat_id, *([] if position is None else position), limit + 1),
    )
    page = found[:limit]
    following = token.encode([page[-1]["sequence"]]) if len(found) > limit else None
    return {
        "items": [message_public(item, session) for item in reversed(page)],
        "older_cursor": following,
    }


def message_public(item: dict, session: UserSession) -> dict:
    result = public(item)
    unavailable = item["role"] == "aqua" and (
        not session.can_query or item.get("dataset_key") != session.dataset_key
    )
    result["result_unavailable"] = unavailable
    if item["role"] == "user":
        result["response"] = None
    elif unavailable:
        result["response"] = None
        result["content"] = ""
    else:
        result.setdefault("response", None)
    return result


def patch_chat(conn: Connection, owner: str, chat_id: str, body: BaseModel) -> dict:
    current = chat_row(conn, owner, chat_id, lock=True)
    if current["revision"] != body.revision:
        raise WorkspaceError("revision_conflict", 409)
    changes = body.model_dump(exclude_unset=True, exclude={"revision"})
    if "title" in changes:
        allocate(
            conn, owner, len(changes["title"].encode()) - len(current["title"].encode())
        )
    if "project_id" in changes:
        project_exists(
            conn, owner, str(changes["project_id"]) if changes["project_id"] else None
        )
    # Field names come only from a closed validated model.
    assignments = [f"{key}=%s" for key in changes]
    item = one(
        conn,
        f"UPDATE app.chats SET {','.join(assignments)},revision=revision+1 WHERE user_id=%s AND id=%s RETURNING {CHAT}",
        (*changes.values(), owner, chat_id),
    )
    return {"chat": public(item)}


def delete_chat(conn: Connection, owner: str, chat_id: str, revision: int) -> None:
    current = chat_row(conn, owner, chat_id, lock=True)
    if current["revision"] != revision:
        raise WorkspaceError("revision_conflict", 409)
    size = conn.execute(
        "SELECT COALESCE(sum(octet_length(content)),0) FROM app.messages WHERE user_id=%s AND chat_id=%s",
        (owner, chat_id),
    ).fetchone()[0]
    size += conn.execute(
        "SELECT COALESCE(sum(octet_length(response::text)),0) FROM app.visual_results WHERE user_id=%s AND chat_id=%s",
        (owner, chat_id),
    ).fetchone()[0]
    size += len(current["title"].encode())
    size += conn.execute(
        "SELECT COALESCE(sum(reserved_bytes),0) FROM app.analysis_requests WHERE user_id=%s AND chat_id=%s",
        (owner, chat_id),
    ).fetchone()[0]
    allocate(conn, owner, -size)
    conn.execute(
        "DELETE FROM app.visual_results WHERE user_id=%s AND chat_id=%s",
        (owner, chat_id),
    )
    conn.execute(
        "UPDATE app.messages SET content='',status=CASE WHEN status='pending' THEN 'interrupted' ELSE status END WHERE user_id=%s AND chat_id=%s",
        (owner, chat_id),
    )
    conn.execute(
        "UPDATE app.analysis_requests SET fingerprint=decode(repeat('00',32),'hex'),reserved_bytes=0,state=CASE WHEN state='pending' THEN 'interrupted' ELSE state END WHERE user_id=%s AND chat_id=%s",
        (owner, chat_id),
    )
    conn.execute(
        "UPDATE app.chats SET deleted_at=clock_timestamp(),title='Deleted chat',project_id=NULL,revision=revision+1 WHERE user_id=%s AND id=%s",
        (owner, chat_id),
    )
