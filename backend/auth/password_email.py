"""Bounded mailbox requests enqueue encrypted jobs, never reserve identity."""

import secrets

from auth.mailconfig import MailPolicy
from auth.mailoutbox import enqueue, ensure_capacity
from auth.mailrecipient import allowed
from auth.password_limits import LOCK, cleanup_password_challenges
from auth.password_policy import PasswordPolicy
from auth.password_records import token_digest
from storage.pool import Storage


def request_email(
    storage: Storage,
    policy: PasswordPolicy,
    mail_policy: MailPolicy,
    email: str,
    purpose: str,
) -> None:
    """No credential exists until a mailbox token and freshly chosen password meet.

    The same admission, capacity checks and bounded queries run for unavailable
    mailboxes. Eligibility affects only the encrypted outbox insertion; external
    sending never runs on a request thread or under this transaction.
    """
    with storage.transaction() as conn:
        ensure_capacity(
            conn,
            mail_policy,
            purpose="verify_email" if purpose == "verify_email" else "reset_password",
        )
        if not allowed(
            conn,
            email,
            "verify_email" if purpose == "verify_email" else "reset_password",
        ):
            return
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        cleanup_password_challenges(conn, policy)
        row = conn.execute(
            "SELECT u.id,u.status,u.auth_epoch,p.user_id IS NOT NULL FROM app.user_emails e "
            "JOIN app.users u ON u.id=e.user_id LEFT JOIN app.password_credentials p ON p.user_id=u.id "
            "WHERE e.email_key=%s AND e.is_primary AND e.verified_at IS NOT NULL",
            (email,),
        ).fetchone()
        pending = conn.execute(
            "SELECT id FROM app.auth_challenges WHERE target_email_key=%s AND purpose=%s "
            "AND consumed_at IS NULL AND expires_at>now() LIMIT 3",
            (email, purpose),
        ).fetchall()
        eligible = (
            row is None
            if purpose == "verify_email"
            else bool(row and row[1] == "active" and row[3])
        )
        if not eligible or len(pending) >= 3:
            return
        owner, epoch = (None, None) if row is None else (row[0], row[2])
        token = secrets.token_urlsafe(32)
        seconds = (
            policy.verification_seconds
            if purpose == "verify_email"
            else policy.reset_seconds
        )
        expiry = conn.execute(
            "SELECT clock_timestamp()+%s*interval '1 second'", (seconds,)
        ).fetchone()[0]
        ticket = conn.execute(
            "INSERT INTO app.auth_challenges(purpose,user_id,secret_digest,target_email_key,password_auth_epoch,expires_at) "
            "VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
            (purpose, owner, token_digest(token), email, epoch, expiry),
        ).fetchone()[0]
        enqueue(
            conn,
            recipient=email,
            purpose="verify_email" if purpose == "verify_email" else "reset_password",
            token=token,
            expires_at=expiry,
            policy=mail_policy,
            challenge_id=ticket,
        )
