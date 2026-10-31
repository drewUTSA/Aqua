"""Canonical credential snapshots for detached work; never caller-selected email."""

from dataclasses import dataclass, field
from datetime import datetime

from psycopg import Connection

from workspace.errors import WorkspaceError


@dataclass(frozen=True)
class PasswordSnapshot:
    encoded: str = field(repr=False)
    changed_at: datetime
    email: str = field(repr=False)


def password_snapshot(conn: Connection, owner: str) -> PasswordSnapshot:
    row = conn.execute(
        "SELECT p.encoded_hash,p.changed_at,e.email_key FROM app.password_credentials p "
        "JOIN app.user_emails e ON e.user_id=p.user_id "
        "AND e.is_primary AND e.verified_at IS NOT NULL WHERE p.user_id=%s",
        (owner,),
    ).fetchone()
    if row is None:
        raise WorkspaceError("method_unavailable", 403)
    return PasswordSnapshot(*row)
