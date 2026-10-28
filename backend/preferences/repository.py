"""Owner-scoped preferences use the existing schema-5 table and atomic revision."""

from copy import deepcopy
from psycopg import Connection
from psycopg.types.json import Jsonb
from preferences.contracts import PreferenceUpdate
from preferences.schema import CAPABILITIES, MAX_REVISION, VERSION, validate_values
from workspace.errors import WorkspaceError


def read(conn: Connection, owner: str) -> dict:
    row = conn.execute(
        "SELECT schema_version,revision,values FROM app.user_preferences WHERE user_id=%s",
        (owner,),
    ).fetchone()
    if row is None:
        # Identity creation normally writes this row. An absent record may use
        # safe defaults, and its first write still uses revision 1 atomically.
        return envelope(1, {})
    version, revision, values = row
    if version != VERSION:
        raise WorkspaceError("unsupported_schema", 409)
    return envelope(revision, values)


def envelope(revision: int, values: dict) -> dict:
    if type(revision) is not int or not 1 <= revision <= MAX_REVISION:
        raise WorkspaceError("service_unavailable", 503)
    try:
        canonical = validate_values(values, complete=False)
    except ValueError:
        # Corrupt/current-version unknown fields must not be discarded by a
        # later full-snapshot save. Keep the original row for explicit repair.
        raise WorkspaceError("service_unavailable", 503) from None
    return {
        "schemaVersion": VERSION,
        "revision": revision,
        "values": canonical,
        "capabilities": deepcopy(CAPABILITIES),
    }


def save(conn: Connection, owner: str, body: PreferenceUpdate) -> dict:
    current = read(conn, owner)
    if current["revision"] != body.expectedRevision:
        raise WorkspaceError("revision_conflict", 409)
    if current["revision"] >= MAX_REVISION:
        raise WorkspaceError("service_unavailable", 503)
    conn.execute(
        "INSERT INTO app.user_preferences(user_id) VALUES(%s) ON CONFLICT DO NOTHING",
        (owner,),
    )
    row = conn.execute(
        "UPDATE app.user_preferences SET values=%s,revision=revision+1,updated_at=clock_timestamp() "
        "WHERE user_id=%s AND revision=%s AND schema_version=%s RETURNING revision,values",
        (Jsonb(body.values), owner, body.expectedRevision, VERSION),
    ).fetchone()
    if row is None:
        raise WorkspaceError("revision_conflict", 409)
    return envelope(*row)
