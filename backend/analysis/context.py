"""Freeze earlier owned questions and validated SQL, never result rows or summaries."""

import hashlib
import json
from psycopg import Connection

from analysis.policy import MAX_CONTEXT_BYTES
from bank_demo.cash_chat import is_private_cash_input
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
    conn: Connection,
    owner: str,
    chat: str,
    sequence: int,
    dataset: str,
    grant: int,
    *,
    exclude_bank_inputs: bool = False,
) -> tuple[list[dict], bytes]:
    candidates = rows(
        conn,
        """
        WITH recent AS (
            SELECT m.id, m.sequence, m.content, r.state, r.dataset_key, r.grant_version, v.response
            FROM app.messages m
            JOIN app.analysis_requests r ON r.user_id=m.user_id AND r.chat_id=m.chat_id AND r.id=m.request_id
            LEFT JOIN app.visual_results v ON v.user_id=r.user_id AND v.chat_id=r.chat_id AND v.request_id=r.id
            WHERE m.user_id=%s AND m.chat_id=%s AND m.role='user' AND m.sequence<%s
              AND (v.response->'bank_cash_reply') IS DISTINCT FROM 'true'::jsonb
            ORDER BY m.sequence DESC LIMIT 8
        )
        SELECT id, sequence, content,
               CASE WHEN response->>'status'='success' AND jsonb_typeof(response->'sql')='string'
                         AND octet_length(convert_to(response->>'sql', 'UTF8'))<=4096
                    THEN response->>'sql' END AS sql
        FROM recent
        WHERE state='complete' AND dataset_key=%s AND grant_version=%s
        ORDER BY sequence DESC
        """,
        (owner, chat, sequence, dataset, grant),
    )
    chosen, sql_count = [], 0
    for item in candidates:
        if exclude_bank_inputs and is_private_cash_input(item["content"]):
            continue
        record = {
            "message_id": str(item["id"]),
            "sequence": item["sequence"],
            "question": item["content"],
        }
        if sql_count < 2 and item["sql"] is not None:
            record["sql"] = item["sql"]
            sql_count += 1
        if len(encode([record, *chosen])) <= MAX_CONTEXT_BYTES:
            chosen.insert(0, record)
    return chosen, hashlib.sha256(encode(chosen)).digest()
