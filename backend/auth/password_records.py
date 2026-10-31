"""Transactional password-email tickets; pending requests never own an account."""

from dataclasses import dataclass, field
import hashlib

import psycopg

from auth.config import AuthDenied
from auth.mailconfig import MailPolicy
from auth.mailoutbox import LOCK as MAIL_LOCK, enqueue, ensure_capacity
from auth.password_limits import digest_key


@dataclass(frozen=True)
class EmailTicket:
    id: str
    purpose: str
    email: str
    owner: str | None
    epoch: int | None


@dataclass(frozen=True)
class PasswordCandidate:
    owner: str
    email: str
    epoch: int
    encoded: str | None = field(repr=False)
    active: bool = False


def token_digest(token: str) -> bytes:
    return hashlib.sha256(token.encode("ascii")).digest()


def find_ticket(
    conn: psycopg.Connection, token: str, purpose: str, *, lock: bool = False
) -> EmailTicket:
    row = conn.execute(
        "SELECT id,target_email_key,user_id,password_auth_epoch FROM app.auth_challenges "
        "WHERE secret_digest=%s AND purpose=%s AND consumed_at IS NULL AND expires_at>clock_timestamp()"
        + (" FOR UPDATE" if lock else ""),
        (token_digest(token), purpose),
    ).fetchone()
    if row is None:
        raise AuthDenied("email_challenge_invalid")
    return EmailTicket(
        str(row[0]), purpose, row[1], str(row[2]) if row[2] else None, row[3]
    )


def create_verified_account(
    conn: psycopg.Connection, ticket: EmailTicket, encoded: str, version: int
) -> str:
    # Completion retires old verification jobs, so it participates in the same
    # mail -> address ordering as an authenticated primary-mail change. Merely
    # taking the closed lock does not require mail delivery to remain enabled.
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (MAIL_LOCK,))
    lock = int.from_bytes(digest_key(ticket.email)[:8], "big", signed=True)
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    # Reload after acquiring the per-address lock: parallel tokens may have
    # become consumed while Argon2 deliberately ran without a DB connection.
    valid = conn.execute(
        "SELECT id FROM app.auth_challenges WHERE id=%s AND purpose='verify_email' "
        "AND user_id IS NULL AND consumed_at IS NULL AND expires_at>clock_timestamp() FOR UPDATE",
        (ticket.id,),
    ).fetchone()
    if valid is None:
        raise AuthDenied("email_challenge_invalid")
    owner = conn.execute(
        "INSERT INTO app.users(status) VALUES ('active') RETURNING id"
    ).fetchone()[0]
    address = conn.execute(
        "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) "
        "VALUES (%s,%s,%s,now(),'email',true) ON CONFLICT(email_key) DO NOTHING RETURNING id",
        (owner, ticket.email, ticket.email),
    ).fetchone()
    if address is None:
        # Raising rolls the provisional user back too. Matching email never
        # changes or links a pre-existing Google/password identity.
        raise AuthDenied("email_challenge_invalid")
    conn.execute(
        "INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version) VALUES (%s,%s,%s)",
        (owner, encoded, version),
    )
    conn.execute("INSERT INTO app.user_preferences(user_id) VALUES (%s)", (owner,))
    conn.execute(
        "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() WHERE target_email_key=%s AND purpose='verify_email' AND consumed_at IS NULL",
        (ticket.email,),
    )
    conn.execute(
        "DELETE FROM app.account_mail m USING app.auth_challenges c "
        "WHERE m.challenge_id=c.id AND c.target_email_key=%s "
        "AND c.purpose='verify_email' AND c.consumed_at IS NOT NULL",
        (ticket.email,),
    )
    return str(owner)


def replace_password(
    conn: psycopg.Connection,
    ticket: EmailTicket,
    encoded: str,
    version: int,
    mail_policy: MailPolicy,
) -> None:
    ensure_capacity(conn, mail_policy)
    state = conn.execute(
        "SELECT status,auth_epoch FROM app.users WHERE id=%s FOR UPDATE",
        (ticket.owner,),
    ).fetchone()
    current = conn.execute(
        "SELECT c.id FROM app.auth_challenges c JOIN app.user_emails e ON e.user_id=c.user_id "
        "AND e.email_key=c.target_email_key AND e.is_primary AND e.verified_at IS NOT NULL "
        "JOIN app.password_credentials p ON p.user_id=c.user_id WHERE c.id=%s "
        "AND c.purpose='password_reset' AND c.consumed_at IS NULL AND c.expires_at>clock_timestamp() "
        "AND c.password_auth_epoch=%s FOR UPDATE OF c",
        (ticket.id, ticket.epoch),
    ).fetchone()
    if state is None or state != ("active", ticket.epoch) or current is None:
        raise AuthDenied("email_challenge_invalid")
    conn.execute(
        "UPDATE app.password_credentials SET encoded_hash=%s,policy_version=%s,changed_at=clock_timestamp() WHERE user_id=%s",
        (encoded, version, ticket.owner),
    )
    conn.execute(
        "UPDATE app.users SET auth_epoch=auth_epoch+1,updated_at=clock_timestamp() WHERE id=%s",
        (ticket.owner,),
    )
    # Epoch invalidation covers all history in O(log users). This indexed update
    # marks the bounded currently usable set; old expired rows already deny.
    conn.execute(
        "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE user_id=%s AND auth_epoch=%s AND revoked_at IS NULL AND idle_expires_at>now()",
        (ticket.owner, ticket.epoch),
    )
    conn.execute(
        "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() WHERE user_id=%s AND purpose='password_reset' AND consumed_at IS NULL",
        (ticket.owner,),
    )
    conn.execute(
        "DELETE FROM app.account_mail m USING app.auth_challenges c "
        "WHERE m.challenge_id=c.id AND c.user_id=%s AND c.purpose='password_reset' "
        "AND c.consumed_at IS NOT NULL",
        (ticket.owner,),
    )
    expiry = conn.execute("SELECT clock_timestamp()+interval '1 hour'").fetchone()[0]
    enqueue(
        conn,
        recipient=ticket.email,
        purpose="password_changed",
        token=None,
        expires_at=expiry,
        policy=mail_policy,
    )


def find_candidate(conn: psycopg.Connection, email: str) -> PasswordCandidate | None:
    row = conn.execute(
        "SELECT u.id,e.address,u.auth_epoch,p.encoded_hash,u.status FROM app.user_emails e "
        "JOIN app.users u ON u.id=e.user_id LEFT JOIN app.password_credentials p ON p.user_id=u.id "
        "WHERE e.email_key=%s AND e.is_primary AND e.verified_at IS NOT NULL",
        (email,),
    ).fetchone()
    return (
        PasswordCandidate(str(row[0]), row[1], row[2], row[3], row[4] == "active")
        if row
        else None
    )
