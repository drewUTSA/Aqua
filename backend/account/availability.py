"""Method-specific authority comes from server policy, never preferences."""

import os

from psycopg import Connection

from account.policy import CAPABILITIES
from auth.mailconfig import MailUnavailable, load_mail_policy


def capabilities(conn: Connection, owner: str, origin: str) -> dict[str, bool]:
    result = {**CAPABILITIES, "password_add": False}
    password = conn.execute(
        "SELECT 1 FROM app.password_credentials WHERE user_id=%s", (owner,)
    ).fetchone()
    available = (
        password is not None
        and os.environ.get("PASSWORD_AUTH_ENABLED", "false") == "true"
    )
    result.update(
        recent_proof=available, session_revoke=available, sessions_revoke_all=available
    )
    try:
        mail = load_mail_policy()
        mail_ready = mail.enabled and mail.public_origin == origin
    except MailUnavailable:
        mail_ready = False
    result["password_change"] = available and mail_ready
    return result
