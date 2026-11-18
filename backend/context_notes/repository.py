"""Explicit PostgreSQL adapter; canonical owner locks are held by the service."""

import hashlib

from psycopg import Connection

from context_notes import rules
from context_notes.policy import (
    MAX_ACTIVE,
    MAX_GLOBAL_ROWS,
    MAX_OWNER_ROWS,
    MAX_REVISION,
)
from workspace.database import allocate, one, rows
from workspace.errors import WorkspaceError

FIELDS = (
    "id,user_id,dataset_key,grant_version,kind,label,body,revision,"
    "client_request_id,fingerprint,content_bytes,created_at,updated_at,deleted_at"
)


def listing(conn: Connection, owner: str) -> list[dict]:
    found = rows(
        conn,
        "SELECT id,dataset_key,grant_version,kind,label,revision,created_at,updated_at "
        "FROM app.context_notes WHERE user_id=%s AND deleted_at IS NULL "
        "ORDER BY updated_at DESC,id DESC LIMIT %s",
        (owner, MAX_ACTIVE + 1),
    )
    if len(found) > MAX_ACTIVE:
        raise WorkspaceError("service_unavailable", 503)
    return found


def get(conn: Connection, owner: str, note_id: str) -> dict:
    item = one(
        conn,
        f"SELECT {FIELDS} FROM app.context_notes "
        "WHERE user_id=%s AND id=%s AND deleted_at IS NULL FOR UPDATE",
        (owner, note_id),
    )
    if item is None:
        raise WorkspaceError("not_found")
    return item


def create(
    conn: Connection, owner: str, dataset: str, version: int, body
) -> tuple[dict, int]:
    values = rules.content(body.kind, body.label, body.body)
    digest = hashlib.sha256(rules.encode([dataset, version, values])).digest()
    existing = one(
        conn,
        f"SELECT {FIELDS} FROM app.context_notes "
        "WHERE user_id=%s AND client_request_id=%s FOR UPDATE",
        (owner, body.client_request_id),
    )
    if existing:
        if existing["deleted_at"] is not None:
            raise WorkspaceError("not_found")
        if (
            existing["dataset_key"] != dataset
            or existing["grant_version"] != version
            or bytes(existing["fingerprint"]) != digest
        ):
            raise WorkspaceError("idempotency_conflict", 409)
        return existing, 200
    # The existing global bookkeeping lock serializes new-row capacity too.
    allocate(conn, owner, 0)
    counts = conn.execute(
        "SELECT count(*),count(*) FILTER (WHERE deleted_at IS NULL) "
        "FROM app.context_notes WHERE user_id=%s",
        (owner,),
    ).fetchone()
    total = conn.execute("SELECT count(*) FROM app.context_notes").fetchone()[0]
    if (
        counts[0] >= MAX_OWNER_ROWS
        or counts[1] >= MAX_ACTIVE
        or total >= MAX_GLOBAL_ROWS
    ):
        raise WorkspaceError("capacity_reached", 429)
    size = len(body.label.encode()) + len(body.body.encode())
    allocate(conn, owner, size)
    item = one(
        conn,
        f"INSERT INTO app.context_notes(user_id,dataset_key,grant_version,kind,label,body,"
        f"client_request_id,fingerprint,content_bytes) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {FIELDS}",
        (
            owner,
            dataset,
            version,
            body.kind,
            body.label,
            body.body,
            body.client_request_id,
            digest,
            size,
        ),
    )
    return item, 201


def patch(conn: Connection, owner: str, item: dict, body) -> dict:
    check_revision(item, body.revision)
    if item["revision"] >= MAX_REVISION:
        raise WorkspaceError("service_unavailable", 503)
    size = len(body.label.encode()) + len(body.body.encode())
    allocate(conn, owner, size - item["content_bytes"])
    return one(
        conn,
        f"UPDATE app.context_notes SET kind=%s,label=%s,body=%s,content_bytes=%s,"
        f"revision=revision+1,updated_at=clock_timestamp() WHERE user_id=%s AND id=%s RETURNING {FIELDS}",
        (body.kind, body.label, body.body, size, owner, item["id"]),
    )


def check_revision(item: dict, expected: int) -> None:
    if item["revision"] != expected:
        raise WorkspaceError("revision_conflict", 409)


def forget(conn: Connection, owner: str, item: dict, expected: int) -> dict:
    check_revision(item, expected)
    if item["revision"] >= MAX_REVISION:
        raise WorkspaceError("service_unavailable", 503)
    allocate(conn, owner, -item["content_bytes"])
    updated = one(
        conn,
        "UPDATE app.context_notes SET label='Deleted context',body='',content_bytes=0,"
        "fingerprint=decode(repeat('00',32),'hex'),revision=revision+1,"
        "deleted_at=clock_timestamp(),updated_at=clock_timestamp() "
        "WHERE user_id=%s AND id=%s RETURNING id,revision",
        (owner, item["id"]),
    )
    return {"id": str(updated["id"]), "revision": updated["revision"]}
