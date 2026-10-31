"""Explicit in-app notice settings; no browser permission or mail subscription."""

from account.policy import MAX_REVISION
from workspace.database import guard, admit
from workspace.errors import WorkspaceError

CAPABILITIES = {
    "in_app": True,
    "browser": False,
    "email": False,
    "sound": False,
    "quiet_hours": False,
}


def execute(store, session, body=None):
    with store.storage.transaction() as conn:
        guard(conn, session, store.policy)
        admit(conn, session.user["id"])
    with store.storage.transaction() as conn:
        guard(conn, session, store.policy)
        row = conn.execute(
            "SELECT revision,in_app_success,preview FROM app.user_notification_settings WHERE user_id=%s",
            (session.user["id"],),
        ).fetchone() or (1, False, "generic")
        if body is not None:
            if row[0] != body.expectedRevision:
                raise WorkspaceError("revision_conflict", 409)
            if row[1:] != (body.in_app_success, body.preview):
                if row[0] >= MAX_REVISION:
                    raise WorkspaceError("security_unavailable", 503)
                row = conn.execute(
                    "INSERT INTO app.user_notification_settings(user_id,revision,in_app_success,preview) VALUES(%s,%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET revision=EXCLUDED.revision,in_app_success=EXCLUDED.in_app_success,preview=EXCLUDED.preview,updated_at=clock_timestamp() RETURNING revision,in_app_success,preview",
                    (session.user["id"], row[0] + 1, body.in_app_success, body.preview),
                ).fetchone()
        return {
            "schemaVersion": 1,
            "user_id": session.user["id"],
            "revision": row[0],
            "values": {"in_app_success": row[1], "preview": row[2]},
            "capabilities": dict(CAPABILITIES),
        }
