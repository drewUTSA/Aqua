"""Freeze earlier owned questions and validated SQL, never result rows or summaries."""

import hashlib
import json
from psycopg import Connection

from analysis.policy import MAX_CONTEXT_BYTES
from workspace.database import rows


def encode(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        allow_nan=False,
    ).encode()


def select(
    conn: Connection, owner: str, chat: str, sequence: int, dataset: str, grant: int
) -> tuple[list[dict], bytes]:
    candidates = rows(
        conn,
        "SELECT m.id,m.sequence,m.content,r.state,r.dataset_key,r.grant_version,v.response "
        "FROM app.messages m JOIN app.analysis_requests r ON r.user_id=m.user_id AND r.chat_id=m.chat_id AND r.id=m.request_id "
        "LEFT JOIN app.visual_results v ON v.user_id=r.user_id AND v.chat_id=r.chat_id AND v.request_id=r.id "
        "WHERE m.user_id=%s AND m.chat_id=%s AND m.role='user' AND m.sequence<%s ORDER BY m.sequence DESC LIMIT 8",
        (owner, chat, sequence),
    )
    chosen, sql_count = [], 0
    for item in candidates:
        # Incomplete/failed or previous-grant answers cannot become implicit context.
        if (
            item["state"] != "complete"
            or item["dataset_key"] != dataset
            or item["grant_version"] != grant
        ):
            continue
        record = {
            "message_id": str(item["id"]),
            "sequence": item["sequence"],
            "question": item["content"],
        }
        response = item.get("response") or {}
        sql = response.get("sql")
        if (
            sql_count < 2
            and response.get("status") == "success"
            and isinstance(sql, str)
            and len(sql.encode()) <= 4096
        ):
            record["sql"] = sql
            sql_count += 1
        if len(encode([record, *chosen])) <= MAX_CONTEXT_BYTES:
            chosen.insert(0, record)
    return chosen, hashlib.sha256(encode(chosen)).digest()
