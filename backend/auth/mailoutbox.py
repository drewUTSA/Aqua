"""Atomic encrypted account-mail admission; a committed challenge and job agree."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import secrets
import uuid

from psycopg import Connection

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from auth.mailconfig import MailPolicy, MailUnavailable
from auth.mailproof import validate_challenge
from auth.mailrecipient import reserve
from auth.mailtemplates import render, validate
from auth.mailpurposes import ACCOUNT_TOKENS, GROUPS, NOTICES, PURPOSES, group

LOCK = 1095848261
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True)
class MailJob:
    id: uuid.UUID
    purpose: str
    recipient_digest: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)
    expires_at: datetime
    lease_id: uuid.UUID
    attempts: int


def _aad(
    job_id: uuid.UUID,
    purpose: str,
    recipient_digest: bytes,
    expires_at: datetime,
) -> bytes:
    return json.dumps(
        [
            str(job_id),
            purpose,
            recipient_digest.hex(),
            expires_at.astimezone(timezone.utc).isoformat(),
        ],
        separators=(",", ":"),
    ).encode()


def ensure_capacity(
    conn: Connection, policy: MailPolicy, purpose: str | None = None, *, count: int = 1
) -> None:
    """Call before checking account eligibility, so overload cannot enumerate it.

    A short shared lock bounds all retained rows and pending work. Purging is
    indexed/batched. No live quota/job is evicted to make admission succeed.
    """
    if (
        type(count) is not int
        or not 1 <= count <= 2
        or purpose is not None
        and purpose not in PURPOSES
    ):
        raise MailUnavailable("account_mail_input_invalid")
    if not policy.enabled or len(policy.key) != 32:
        raise MailUnavailable("account_mail_disabled")
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    conn.execute(
        "DELETE FROM app.account_mail WHERE id IN (SELECT id FROM app.account_mail "
        "WHERE expires_at<=now() ORDER BY expires_at,id LIMIT %s FOR UPDATE SKIP LOCKED)",
        (policy.cleanup_batch,),
    )
    rows, pending = conn.execute(
        "SELECT count(*),count(*) FILTER (WHERE state IN ('pending','sending')) FROM app.account_mail"
    ).fetchone()
    if rows + count > policy.max_rows or pending + count > policy.max_pending:
        raise MailUnavailable("account_mail_capacity")
    if purpose is not None:
        # Registration can never fill slots reserved for recovery/security mail.
        bucket = group(purpose)
        limit = {"verify_email": 1024, "reset_password": 768, "password_changed": 256}[
            bucket
        ]
        queued = conn.execute(
            "SELECT count(*) FROM app.account_mail WHERE purpose=ANY(%s) AND state IN ('pending','sending')",
            (list(GROUPS[bucket]),),
        ).fetchone()[0]
        if queued + count > min(limit, policy.max_pending):
            raise MailUnavailable("account_mail_capacity")


def enqueue(
    conn: Connection,
    *,
    recipient: str,
    purpose: str,
    token: str | None,
    expires_at: datetime,
    policy: MailPolicy,
    challenge_id: uuid.UUID | None = None,
) -> uuid.UUID:
    ensure_capacity(conn, policy, purpose)
    if (
        purpose not in PURPOSES
        or not isinstance(recipient, str)
        or not 3 <= len(recipient) <= 320
        or recipient.count("@") != 1
        or any(char.isspace() or ord(char) < 32 for char in recipient)
        or not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or (
            purpose not in NOTICES
            and (
                not isinstance(token, str)
                or not TOKEN.fullmatch(token)
                or challenge_id is None
            )
        )
        or (purpose in NOTICES and (token is not None or challenge_id is not None))
    ):
        raise MailUnavailable("account_mail_input_invalid")
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    if not 0 < (expires_at - instant).total_seconds() <= 86400:
        raise MailUnavailable("account_mail_expiry_invalid")
    job_id = uuid.uuid4()
    recipient_digest = hashlib.sha256(recipient.encode()).digest()
    request_id = ""
    if purpose not in NOTICES:
        validate_challenge(conn, recipient, purpose, token, expires_at, challenge_id)
        reserve(conn, recipient, purpose)
        if purpose in ACCOUNT_TOKENS:
            request_id = str(
                conn.execute(
                    "SELECT account_request_id FROM app.auth_challenges WHERE id=%s",
                    (challenge_id,),
                ).fetchone()[0]
            )
    payload = render(
        purpose, recipient, token, policy.public_origin, request_id=request_id
    )
    raw = json.dumps(payload, separators=(",", ":")).encode()
    nonce = secrets.token_bytes(12)
    ciphertext = nonce + AESGCM(policy.key).encrypt(
        nonce, raw, _aad(job_id, purpose, recipient_digest, expires_at)
    )
    if len(ciphertext) > 4096:
        raise MailUnavailable("account_mail_payload_invalid")
    conn.execute(
        "INSERT INTO app.account_mail(id,purpose,recipient_digest,ciphertext,challenge_id,expires_at) "
        "VALUES (%s,%s,%s,%s,%s,%s)",
        (job_id, purpose, recipient_digest, ciphertext, challenge_id, expires_at),
    )
    return job_id


def open_job(job: MailJob, policy: MailPolicy) -> dict[str, str]:
    """Worker-only decryption. A swapped job, recipient, purpose or expiry fails."""
    try:
        if job.purpose not in PURPOSES or not 30 <= len(job.ciphertext) <= 4096:
            raise ValueError
        raw = AESGCM(policy.key).decrypt(
            job.ciphertext[:12],
            job.ciphertext[12:],
            _aad(job.id, job.purpose, job.recipient_digest, job.expires_at),
        )
        payload = json.loads(raw)
        validate(job.purpose, payload, policy.public_origin)
        if hashlib.sha256(payload["to"].encode()).digest() != job.recipient_digest:
            raise ValueError
        return payload
    except (InvalidTag, ValueError, TypeError, KeyError, UnicodeError, MailUnavailable):
        raise MailUnavailable("account_mail_envelope_invalid") from None
