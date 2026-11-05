"""A deletion fences previously staged output within its existing user lock."""

from workspace.errors import WorkspaceError


def advance(conn, owner):
    # Workspace mutations already hold the canonical user row. Taking privacy
    # global here would invert global -> user -> job, so only bump the epoch.
    # The next worker/publication/download check retires stale private output.
    row = conn.execute(
        "UPDATE app.users SET privacy_epoch=privacy_epoch+1 WHERE id=%s AND privacy_epoch<9007199254740991 RETURNING id",
        (owner,),
    ).fetchone()
    if row is None:
        raise WorkspaceError("service_unavailable", 503)
