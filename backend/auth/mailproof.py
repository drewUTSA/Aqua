"""A queued bearer must belong to the exact challenge, mailbox and lifetime."""

from datetime import datetime
import hashlib
import uuid

from psycopg import Connection

from auth.mailconfig import MailUnavailable


def validate_challenge(
    conn: Connection,
    recipient: str,
    purpose: str,
    token: str,
    expires_at: datetime,
    challenge_id: uuid.UUID | None,
) -> None:
    if challenge_id is None:
        raise MailUnavailable("account_mail_challenge_invalid")
    expected = "verify_email" if purpose == "verify_email" else "password_reset"
    row = conn.execute(
        "SELECT c.id FROM app.auth_challenges c WHERE c.id=%s AND c.purpose=%s "
        "AND c.target_email_key=%s AND c.secret_digest=%s AND c.expires_at=%s "
        "AND c.consumed_at IS NULL AND c.expires_at>clock_timestamp() "
        "AND ((c.purpose='verify_email' AND c.user_id IS NULL AND c.password_auth_epoch IS NULL) "
        "OR (c.purpose='password_reset' AND EXISTS (SELECT 1 FROM app.users u "
        "JOIN app.user_emails e ON e.user_id=u.id JOIN app.password_credentials p ON p.user_id=u.id "
        "WHERE u.id=c.user_id AND u.status='active' AND u.auth_epoch=c.password_auth_epoch "
        "AND e.email_key=c.target_email_key AND e.is_primary AND e.verified_at IS NOT NULL)))",
        (
            challenge_id,
            expected,
            recipient,
            hashlib.sha256(token.encode("ascii")).digest(),
            expires_at,
        ),
    ).fetchone()
    if row is None:
        raise MailUnavailable("account_mail_challenge_invalid")
