"""Method-specific authority comes from server policy, never preferences."""

import os

from psycopg import Connection

from account.policy import CAPABILITIES
from auth.mailconfig import MailUnavailable, load_mail_policy
from auth.password_policy import normalize_email
from workspace.errors import WorkspaceError


def capabilities(
    conn: Connection, owner: str, origin: str, *, google_enabled: bool = False
) -> dict[str, bool]:
    result = {**CAPABILITIES, "password_add": False}
    password = conn.execute(
        "SELECT 1 FROM app.password_credentials WHERE user_id=%s", (owner,)
    ).fetchone()
    password_available = (
        password is not None
        and os.environ.get("PASSWORD_AUTH_ENABLED", "false") == "true"
    )
    google = conn.execute(
        "SELECT id FROM app.external_identities WHERE user_id=%s AND is_active LIMIT 21",
        (owner,),
    ).fetchall()
    if len(google) > 20:
        raise WorkspaceError("security_unavailable", 503)
    google_available = bool(google) and google_enabled
    available = password_available or google_available
    result.update(
        recent_proof=available, session_revoke=available, sessions_revoke_all=available
    )
    try:
        mail = load_mail_policy()
        mail_ready = mail.enabled and mail.public_origin == origin
    except MailUnavailable:
        mail_ready = False
    primary = conn.execute(
        "SELECT email_key FROM app.user_emails WHERE user_id=%s AND is_primary AND verified_at IS NOT NULL",
        (owner,),
    ).fetchone()
    try:
        mail_ready = bool(
            mail_ready and primary and normalize_email(primary[0]) == primary[0]
        )
    except RuntimeError:
        mail_ready = False
    result.update(
        password_change=password_available and mail_ready,
        password_add=password is None
        and google_available
        and os.environ.get("PASSWORD_AUTH_ENABLED", "false") == "true"
        and mail_ready,
        email_change=available and mail_ready,
        google_link=available and google_enabled and len(google) < 20 and mail_ready,
        google_unlink=available
        and bool(google)
        and (password_available or google_available and len(google) >= 2)
        and mail_ready,
        in_app_notifications=True,
    )
    return result
