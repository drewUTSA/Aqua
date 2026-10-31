"""Bounded canonical profile, method and live-session views with no secrets."""

from copy import deepcopy
import unicodedata

from psycopg import Connection

from account.contracts import ProfileUpdate
from account.policy import (
    CAPABILITIES,
    MAX_METHODS,
    MAX_REVISION,
    MAX_SESSIONS,
    device_label,
)
from auth.accounts import _picture
from auth.security import UserSession
from workspace.errors import WorkspaceError

LIVE_SESSIONS_SQL = (
    "SELECT id,method,device_label,created_at,authenticated_at,last_activity_at,"
    "idle_expires_at,absolute_expires_at FROM app.sessions "
    "WHERE user_id=%s AND auth_epoch=%s AND revoked_at IS NULL "
    "AND idle_expires_at>%s AND absolute_expires_at>%s LIMIT %s"
)


def provider_email(value):
    """An observed method label, never app-primary verification authority."""
    if (
        type(value) is not str
        or not 3 <= len(value) <= 320
        or value.count("@") != 1
        or not all(value.split("@"))
        or any(
            c.isspace() or unicodedata.category(c).startswith("C") or c in "<>"
            for c in value
        )
    ):
        return None
    return value


def profile(conn: Connection, owner: str) -> dict:
    row = conn.execute(
        "SELECT u.id,u.display_name,u.picture,u.profile_revision,e.address "
        "FROM app.users u JOIN app.user_emails e ON e.user_id=u.id "
        "AND e.is_primary AND e.verified_at IS NOT NULL WHERE u.id=%s",
        (owner,),
    ).fetchone()
    if row is None:
        raise WorkspaceError("session_invalid", 401)
    return {
        "schemaVersion": 1,
        "revision": row[3],
        "user": {
            "id": str(row[0]),
            "name": row[1],
            "picture": _picture(row[2]),
            "email": row[4],
        },
        "email_verified": True,
        "capabilities": deepcopy(CAPABILITIES),
    }


def save_profile(conn: Connection, owner: str, body: ProfileUpdate) -> dict:
    current = profile(conn, owner)
    if current["revision"] != body.expectedRevision:
        raise WorkspaceError("revision_conflict", 409)
    if current["user"]["name"] == body.display_name:
        return current
    if current["revision"] >= MAX_REVISION:
        raise WorkspaceError("service_unavailable", 503)
    conn.execute(
        "UPDATE app.users SET display_name=%s,profile_revision=profile_revision+1,"
        "updated_at=clock_timestamp() WHERE id=%s AND profile_revision=%s",
        (body.display_name, owner, body.expectedRevision),
    )
    return profile(conn, owner)


def methods(
    conn: Connection, owner: str, *, password_enabled: bool, google_enabled: bool
) -> dict:
    password = conn.execute(
        "SELECT changed_at FROM app.password_credentials WHERE user_id=%s", (owner,)
    ).fetchone()
    identities = conn.execute(
        "SELECT id,linked_at,observed_email_key FROM app.external_identities WHERE user_id=%s "
        "AND is_active ORDER BY linked_at,id LIMIT %s",
        (owner, MAX_METHODS + 1),
    ).fetchall()
    if len(identities) > MAX_METHODS:
        raise WorkspaceError("service_unavailable", 503)
    return {
        "schemaVersion": 1,
        "password": {
            "linked": password is not None,
            "available": password is not None and password_enabled,
            "changed_at": password[0].isoformat() if password else None,
        },
        "google": {
            "linked": bool(identities),
            "available": bool(identities) and google_enabled,
            "identities": [
                {
                    "id": str(row[0]),
                    "linked_at": row[1].isoformat(),
                    "email": provider_email(row[2]),
                }
                for row in identities
            ],
        },
        "capabilities": deepcopy(CAPABILITIES),
    }


def sessions(conn: Connection, session: UserSession) -> dict:
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    current = conn.execute(
        "SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s",
        (session.user["id"], session.token_digest),
    ).fetchone()
    records = conn.execute(
        LIVE_SESSIONS_SQL,
        (session.user["id"], session.auth_epoch, instant, instant, MAX_SESSIONS + 1),
    ).fetchall()
    if len(records) > MAX_SESSIONS:
        raise WorkspaceError("service_unavailable", 503)
    if current is None or current[0] not in {row[0] for row in records}:
        raise WorkspaceError("session_invalid", 401)
    # Sort at most twenty live rows in memory; never sort retained history.
    records.sort(
        key=lambda row: (row[0] != current[0], -row[5].timestamp(), str(row[0]))
    )
    return {
        "schemaVersion": 1,
        "items": [
            {
                "id": str(row[0]),
                "method": row[1],
                "device_label": device_label(row[2]),
                "created_at": row[3].isoformat(),
                "authenticated_at": row[4].isoformat(),
                "last_activity_at": row[5].isoformat(),
                "idle_expires_at": row[6].isoformat(),
                "absolute_expires_at": row[7].isoformat(),
                "current": row[0] == current[0],
            }
            for row in records
        ],
        "capabilities": {"revoke_one": False, "revoke_all": False},
    }
