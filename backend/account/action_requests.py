"""Bounded pending actions; mail tokens never reserve an address or credential."""

from dataclasses import dataclass
from datetime import datetime

from account.identity_runtime import primary
from account.policy import target_digest
from auth.config import AuthDenied, AuthLimited
from auth.password_policy import normalize_email
from workspace.errors import WorkspaceError

LOCK = 1095848266


@dataclass(frozen=True)
class Pending:
    id: str
    operation: str
    source_email: str
    target_email: str | None
    expires_at: datetime
    google_subject: str | None
    google_email: str | None
    google_authoritative: bool
    source_google_id: str | None
    source_google_revision: int | None
    created_at: datetime
    claimed_at: datetime | None
    verified_at: datetime | None


def create(
    conn, session, sid, operation, target, secret, binding, *, google_snapshot=None
):
    source = primary(conn, session.user["id"])
    try:
        if normalize_email(source[1]) != source[1]:
            raise AuthDenied("account_mailbox_invalid")
    except AuthDenied:
        raise WorkspaceError("method_unavailable", 403) from None
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    conn.execute(
        "DELETE FROM app.account_security_requests WHERE id IN (SELECT id FROM app.account_security_requests WHERE expires_at<=clock_timestamp() ORDER BY expires_at,id LIMIT 64 FOR UPDATE SKIP LOCKED)"
    )
    if (
        len(
            conn.execute(
                "SELECT id FROM app.account_security_requests LIMIT 1024"
            ).fetchall()
        )
        >= 1024
        or len(
            conn.execute(
                "SELECT id FROM app.account_security_requests WHERE user_id=%s LIMIT 3",
                (session.user["id"],),
            ).fetchall()
        )
        >= 3
    ):
        raise AuthLimited(60)
    google_id, revision = google_snapshot or (None, None)
    row = conn.execute(
        "INSERT INTO app.account_security_requests(user_id,session_id,auth_epoch,operation,secret_digest,binding_digest,target_digest,source_email_id,source_email_key,source_email_revision,target_email_key,source_google_identity_id,source_google_identity_revision,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,statement_timestamp(),statement_timestamp()+%s*interval '1 second') RETURNING id,expires_at",
        (
            session.user["id"],
            sid,
            session.auth_epoch,
            operation,
            secret,
            binding,
            target_digest(operation, target),
            source[0],
            source[1],
            source[2],
            target,
            google_id,
            revision,
            300 if operation == "google_link" else 1800,
        ),
    ).fetchone()
    return str(row[0]), row[1]


def load(conn, session, operation, secret, binding, *, request_id=None):
    row = conn.execute(
        "SELECT r.id,r.operation,r.source_email_key,r.target_email_key,r.expires_at,r.google_subject,r.google_email_key,r.google_email_authoritative,r.source_google_identity_id,r.source_google_identity_revision,r.created_at,r.claimed_at,r.verified_at FROM app.account_security_requests r JOIN app.users u ON u.id=r.user_id JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary AND e.verified_at IS NOT NULL WHERE r.user_id=%s AND r.session_id=(SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s) AND r.auth_epoch=%s AND r.operation=%s AND r.secret_digest=%s AND r.binding_digest=%s AND (%s::uuid IS NULL OR r.id=%s) AND r.consumed_at IS NULL AND r.expires_at>clock_timestamp() AND u.email_revision=r.source_email_revision AND e.id=r.source_email_id AND e.email_key=r.source_email_key AND (r.source_google_identity_id IS NULL OR EXISTS(SELECT 1 FROM app.external_identities g WHERE g.user_id=u.id AND g.id=r.source_google_identity_id AND g.is_active AND g.revision=r.source_google_identity_revision)) FOR UPDATE OF r",
        (
            session.user["id"],
            session.user["id"],
            session.token_digest,
            session.auth_epoch,
            operation,
            secret,
            binding,
            request_id,
            request_id,
        ),
    ).fetchone()
    if row is None:
        raise WorkspaceError("proof_invalid", 403)
    return Pending(str(row[0]), *row[1:])


def consume(conn, pending):
    if (
        conn.execute(
            "UPDATE app.account_security_requests SET consumed_at=clock_timestamp() WHERE id=%s AND consumed_at IS NULL AND expires_at>clock_timestamp() RETURNING id",
            (pending.id,),
        ).fetchone()
        is None
    ):
        raise WorkspaceError("proof_invalid", 403)
