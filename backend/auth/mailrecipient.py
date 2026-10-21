"""Recipient-purpose issuance ceilings survive deleted challenges and mail jobs."""

import hashlib
from datetime import timedelta

from psycopg import Connection

from auth.mailconfig import MailUnavailable
from auth.mailtemplates import recipient_key

MAX_KEYS = 4096
CLEANUP_BATCH = 64


def allowed(conn: Connection, recipient: str, purpose: str) -> bool:
    """Caller holds the account-mail admission lock; suppression is a generic ACK."""
    if purpose not in {"verify_email", "reset_password"}:
        raise MailUnavailable("account_mail_purpose_invalid")
    digest = hashlib.sha256(recipient_key(recipient).encode()).digest()
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.execute(
        "DELETE FROM app.mail_recipient_budget WHERE (purpose,recipient_digest) IN "
        "(SELECT purpose,recipient_digest FROM app.mail_recipient_budget WHERE expires_at<=%s "
        "ORDER BY expires_at,purpose,recipient_digest LIMIT %s FOR UPDATE SKIP LOCKED)",
        (now, CLEANUP_BATCH),
    )
    row = conn.execute(
        "SELECT issued_at,last_queued_at,expires_at FROM app.mail_recipient_budget WHERE purpose=%s AND recipient_digest=%s",
        (purpose, digest),
    ).fetchone()
    if (
        row
        and row[2] > now
        and (
            sum(instant > now - timedelta(hours=24) for instant in row[0]) >= 3
            or (now - row[1]).total_seconds() < 300
        )
    ):
        return False
    if (
        row is None
        and conn.execute("SELECT count(*) FROM app.mail_recipient_budget").fetchone()[0]
        >= MAX_KEYS
    ):
        return False
    # Already queued work is coalesced, without expiring any issued valid link.
    queued = conn.execute(
        "SELECT 1 FROM app.account_mail m JOIN app.auth_challenges c ON c.id=m.challenge_id WHERE m.purpose=%s AND m.recipient_digest=%s AND m.state IN ('pending','sending') AND m.expires_at>%s AND c.consumed_at IS NULL AND c.expires_at>%s LIMIT 1",
        (purpose, digest, now, now),
    ).fetchone()
    return queued is None


def reserve(conn: Connection, recipient: str, purpose: str) -> None:
    if not allowed(conn, recipient, purpose):
        raise MailUnavailable("account_mail_recipient_limited")
    digest = hashlib.sha256(recipient.encode()).digest()
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    row = conn.execute(
        "SELECT issued_at FROM app.mail_recipient_budget WHERE purpose=%s AND recipient_digest=%s",
        (purpose, digest),
    ).fetchone()
    issued = (
        [instant for instant in row[0] if instant > now - timedelta(hours=24)]
        if row
        else []
    )
    issued.append(now)
    conn.execute(
        "INSERT INTO app.mail_recipient_budget(purpose,recipient_digest,issued_at,last_queued_at,expires_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT(purpose,recipient_digest) DO UPDATE SET issued_at=EXCLUDED.issued_at,last_queued_at=EXCLUDED.last_queued_at,expires_at=EXCLUDED.expires_at",
        (purpose, digest, issued, now, now + timedelta(hours=24)),
    )
