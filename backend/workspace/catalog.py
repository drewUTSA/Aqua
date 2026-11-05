"""Private flat groups and saved prompts; curated examples stay separate."""

from psycopg import Connection
from uuid import UUID
from pydantic import BaseModel

from workspace.cursors import Cursors, fingerprint
from workspace.database import allocate, bounded_count, one, public, rows
from workspace.errors import WorkspaceError

FIELDS = {
    "projects": "id,name,archived,revision,created_at,updated_at",
    "saved_prompts": "id,label,prompt,pinned,use_count,last_used_at,revision,created_at,updated_at",
}
ENVELOPE = {"projects": "project", "saved_prompts": "saved_prompt"}
STARTERS = [
    {
        "id": "loans-in-debt",
        "title": "Loans currently in debt",
        "prompt": "How many loans are currently in debt?",
    },
    {
        "id": "loan-amount-by-status",
        "title": "Loan amounts by status",
        "prompt": "What is the average loan amount for each loan status?",
    },
    {
        "id": "top-salary-districts",
        "title": "Top districts by salary",
        "prompt": "Which 5 districts have the highest average salary?",
    },
    {
        "id": "accounts-per-year",
        "title": "Accounts opened per year",
        "prompt": "How many accounts were opened each year?",
    },
]


def get_item(
    conn: Connection, table: str, owner: str, item_id: str, *, lock: bool = False
) -> dict:
    item = one(
        conn,
        f"SELECT {FIELDS[table]},fingerprint FROM app.{table} WHERE user_id=%s AND id=%s AND deleted_at IS NULL"
        + (" FOR UPDATE" if lock else ""),
        (owner, item_id),
    )
    if item is None:
        raise WorkspaceError("not_found")
    return item


def listing(
    conn: Connection,
    table: str,
    owner: str,
    secret: str,
    *,
    limit: int,
    cursor: str | None,
    archived: bool = False,
) -> dict:
    token = Cursors(
        secret,
        owner,
        {"kind": table, "archived": archived if table == "projects" else None},
    )
    position = token.decode(cursor)
    values = [owner]
    predicates = ["user_id=%s", "deleted_at IS NULL"]
    if table == "projects":
        predicates.append("archived=%s")
        values.append(archived)
    if position:
        predicates.append("(updated_at,id)<(%s::timestamptz,%s::uuid)")
        values.extend(position)
    found = rows(
        conn,
        f"SELECT {FIELDS[table]} FROM app.{table} WHERE "
        + " AND ".join(predicates)
        + " ORDER BY updated_at DESC,id DESC LIMIT %s",
        (*values, limit + 1),
    )
    page = found[:limit]
    return {
        "items": [public(item) for item in page],
        "next_cursor": (
            token.encode([page[-1]["updated_at"], str(page[-1]["id"])])
            if len(found) > limit
            else None
        ),
    }


def create(conn: Connection, table: str, owner: str, body: BaseModel) -> dict:
    values = body.model_dump(exclude={"client_request_id"})
    digest = fingerprint(values)
    existing = one(
        conn,
        f"SELECT {FIELDS[table]},fingerprint,deleted_at FROM app.{table} WHERE user_id=%s AND client_request_id=%s",
        (owner, body.client_request_id),
    )
    if existing:
        if existing["deleted_at"] is not None:
            raise WorkspaceError("not_found")
        if bytes(existing["fingerprint"]) != digest:
            raise WorkspaceError("idempotency_conflict", 409)
        return {ENVELOPE[table]: public(existing)}
    allocate(conn, owner, 0)
    bounded_count(conn, table, owner, 20 if table == "projects" else 100, active=True)
    bounded_count(conn, table, owner, 1000)
    if conn.execute(f"SELECT count(*) FROM app.{table}").fetchone()[0] >= 50000:
        raise WorkspaceError("capacity_reached", 429)
    allocate(
        conn,
        owner,
        sum(len(value.encode()) for value in values.values() if isinstance(value, str)),
    )
    item = one(
        conn,
        f"INSERT INTO app.{table}(user_id,client_request_id,fingerprint,{','.join(values)}) VALUES(%s,%s,%s,{','.join(['%s'] * len(values))}) RETURNING {FIELDS[table]}",
        (owner, body.client_request_id, digest, *values.values()),
    )
    return {ENVELOPE[table]: public(item)}


def patch(
    conn: Connection, table: str, owner: str, item_id: str, body: BaseModel
) -> dict:
    current = get_item(conn, table, owner, item_id, lock=True)
    if current["revision"] != body.revision:
        raise WorkspaceError("revision_conflict", 409)
    changes = body.model_dump(exclude_unset=True, exclude={"revision"})
    size = sum(
        len(value.encode()) - len(current[key].encode())
        for key, value in changes.items()
        if isinstance(value, str)
    )
    allocate(conn, owner, size)
    assignments = ",".join(f"{key}=%s" for key in changes)
    item = one(
        conn,
        f"UPDATE app.{table} SET {assignments},revision=revision+1,updated_at=clock_timestamp() WHERE user_id=%s AND id=%s RETURNING {FIELDS[table]}",
        (*changes.values(), owner, item_id),
    )
    return {ENVELOPE[table]: public(item)}


def delete(
    conn: Connection, table: str, owner: str, item_id: str, revision: int
) -> None:
    current = get_item(conn, table, owner, item_id, lock=True)
    if current["revision"] != revision:
        raise WorkspaceError("revision_conflict", 409)
    from privacy.retirement import advance

    advance(conn, owner)
    if table == "projects":
        conn.execute(
            "UPDATE app.chats SET project_id=NULL,revision=revision+1 WHERE user_id=%s AND project_id=%s",
            (owner, item_id),
        )
    size = sum(
        len(current[key].encode())
        for key in ({"name"} if table == "projects" else {"label", "prompt"})
    )
    allocate(conn, owner, -size)
    if table == "projects":
        conn.execute(
            "UPDATE app.projects SET name='Deleted project',fingerprint=decode(repeat('00',32),'hex'),archived=true,deleted_at=clock_timestamp(),revision=revision+1 WHERE user_id=%s AND id=%s",
            (owner, item_id),
        )
    else:
        conn.execute(
            "DELETE FROM app.saved_prompt_uses WHERE user_id=%s AND prompt_id=%s",
            (owner, item_id),
        )
        conn.execute(
            "UPDATE app.saved_prompts SET label='Deleted prompt',prompt='Deleted',fingerprint=decode(repeat('00',32),'hex'),pinned=false,use_count=0,last_used_at=NULL,deleted_at=clock_timestamp(),revision=revision+1 WHERE user_id=%s AND id=%s",
            (owner, item_id),
        )


def use_prompt(conn: Connection, owner: str, item_id: str, key: UUID) -> dict:
    item = get_item(conn, "saved_prompts", owner, item_id, lock=True)
    existing = one(
        conn,
        "SELECT prompt_id FROM app.saved_prompt_uses WHERE user_id=%s AND client_request_id=%s",
        (owner, key),
    )
    if existing:
        if str(existing["prompt_id"]) != item_id:
            raise WorkspaceError("idempotency_conflict", 409)
        return {"saved_prompt": public(item)}
    bounded_count(conn, "saved_prompt_uses", owner, 10000)
    if item["use_count"] >= 2147483647:
        raise WorkspaceError("capacity_reached", 429)
    conn.execute(
        "INSERT INTO app.saved_prompt_uses(user_id,prompt_id,client_request_id) VALUES(%s,%s,%s)",
        (owner, item_id, key),
    )
    item = one(
        conn,
        f"UPDATE app.saved_prompts SET use_count=use_count+1,last_used_at=clock_timestamp(),updated_at=clock_timestamp(),revision=revision+1 WHERE user_id=%s AND id=%s RETURNING {FIELDS['saved_prompts']}",
        (owner, item_id),
    )
    return {"saved_prompt": public(item)}
