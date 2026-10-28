"""Canonical Google identity resolution and narrowly proven legacy grants."""

import hashlib
from typing import Any
from urllib.parse import urlsplit

import psycopg

from auth.config import AuthDenied, AuthPolicy

ISSUER = "https://accounts.google.com"


def validate_identity(identity: dict[str, Any]) -> None:
    subject, email = identity.get("sub"), identity.get("email")
    issuer = identity.get("iss", ISSUER)
    if (
        not isinstance(subject, str)
        or not 1 <= len(subject) <= 255
        or not isinstance(email, str)
        or not 3 <= len(email) <= 320
        or email.count("@") != 1
        or not all(email.split("@"))
        or any(ord(char) <= 32 or ord(char) == 127 for char in email)
        or identity.get("email_verified") is not True
        or not isinstance(issuer, str)
        or issuer not in {ISSUER, "accounts.google.com"}
    ):
        raise AuthDenied("google_identity_invalid")


def _picture(value: object) -> str:
    if not isinstance(value, str) or len(value) > 1024:
        return ""
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        safe = url.scheme == "https" and not url.username and not url.password
        safe = safe and (
            host == "googleusercontent.com" or host.endswith(".googleusercontent.com")
        )
        return value if safe else ""
    except ValueError:
        return ""


def resolve_account(conn: psycopg.Connection, identity: dict[str, Any]) -> str:
    """One subject lock plus DB uniqueness resolves first-login races safely.

    Email collisions are a conflict, never evidence for linking accounts. A
    future linking flow requires fresh proof of both methods in its own phase.
    """
    validate_identity(identity)
    subject, email = identity["sub"], identity["email"].lower()
    lock = int.from_bytes(
        hashlib.sha256((ISSUER + "\0" + subject).encode()).digest()[:8],
        "big",
        signed=True,
    )
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
    existing = conn.execute(
        "SELECT u.id,u.status,e.is_active FROM app.external_identities e JOIN app.users u ON u.id=e.user_id "
        "WHERE e.issuer=%s AND e.subject=%s FOR UPDATE OF u",
        (ISSUER, subject),
    ).fetchone()
    owner = str(existing[0]) if existing else None
    if existing and (existing[1] != "active" or not existing[2]):
        raise AuthDenied("account_inactive")
    name = identity.get("name", "")
    name = name[:120] if isinstance(name, str) else ""
    picture = _picture(identity.get("picture", ""))
    if owner is None:
        address = conn.execute(
            "SELECT user_id FROM app.user_emails WHERE email_key=%s", (email,)
        ).fetchone()
        if address:
            raise AuthDenied("identity_conflict")
        owner = str(
            conn.execute(
                "INSERT INTO app.users(status,display_name,picture) VALUES ('active',%s,%s) RETURNING id",
                (name, picture),
            ).fetchone()[0]
        )
        bound_email = conn.execute(
            "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) "
            "VALUES (%s,%s,%s,now(),'google',true) ON CONFLICT(email_key) DO NOTHING RETURNING user_id",
            (owner, identity["email"], email),
        ).fetchone()
        if bound_email is None:
            raise AuthDenied("identity_conflict")
    # A known verified subject owns the existing canonical account. Provider
    # metadata is observation, never permission to replace the app profile or
    # primary mailbox, even when the new observed email belongs to another user.
    hosted_domain = identity.get("hd", "")
    workspace = (
        isinstance(hosted_domain, str)
        and 1 <= len(hosted_domain) <= 253
        and not any(char.isspace() or ord(char) < 32 for char in hosted_domain)
    )
    authoritative = email.rsplit("@", 1)[-1] == "gmail.com" or workspace
    conn.execute(
        "INSERT INTO app.external_identities(user_id,provider,issuer,subject,last_login_at,observed_email_key,email_authoritative) "
        "VALUES (%s,'google',%s,%s,now(),%s,%s) ON CONFLICT(issuer,subject) DO UPDATE "
        "SET last_login_at=now(),observed_email_key=EXCLUDED.observed_email_key,email_authoritative=EXCLUDED.email_authoritative",
        (owner, ISSUER, subject, email, authoritative),
    )
    conn.execute(
        "INSERT INTO app.user_preferences(user_id) VALUES (%s) ON CONFLICT(user_id) DO NOTHING",
        (owner,),
    )
    return owner


def preserve_approved_grant(
    conn: psycopg.Connection, owner: str, policy: AuthPolicy, subject: str
) -> None:
    """Only fresh verifier-derived evidence can seed an absent legacy grant.

    ON CONFLICT does nothing, including for revoked grants. Reauthentication is
    never an implicit operator decision to restore previously removed access.
    """
    if not policy.dataset_key:
        return
    row = conn.execute(
        "SELECT id,subject,observed_email_key,email_authoritative FROM app.external_identities "
        "WHERE user_id=%s AND provider='google' AND issuer=%s AND subject=%s AND is_active",
        (owner, ISSUER, subject),
    ).fetchone()
    if row is None:
        return
    identity_id, subject, email, authoritative = row
    if subject in policy.allowed_google_subs:
        kind, evidence = "google_subject", subject
    elif authoritative and email in policy.allowed_emails:
        kind, evidence = "google_email", email
    else:
        return
    conn.execute(
        "INSERT INTO app.dataset_grants(user_id,dataset_key,approval_kind,approval_identity_id,approval_evidence) "
        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT(user_id,dataset_key) DO NOTHING",
        (owner, policy.dataset_key, kind, identity_id, evidence),
    )


def grant_state(
    conn: psycopg.Connection, owner: str, policy: AuthPolicy
) -> tuple[bool, int]:
    """Current config and current durable grant are both authoritative inputs."""
    if not policy.dataset_key:
        return False, 0
    row = conn.execute(
        "SELECT g.version,g.revoked_at,g.approval_kind,g.approval_evidence,"
        "e.subject,e.observed_email_key,e.email_authoritative,e.is_active FROM app.dataset_grants g "
        "LEFT JOIN app.external_identities e ON e.id=g.approval_identity_id AND e.user_id=g.user_id "
        "WHERE g.user_id=%s AND g.dataset_key=%s",
        (owner, policy.dataset_key),
    ).fetchone()
    if row is None:
        return False, 0
    version, revoked, kind, evidence, subject, email, authoritative, active = row
    allowed = kind == "operator"
    if kind == "google_subject":
        allowed = (
            active and evidence == subject and evidence in policy.allowed_google_subs
        )
    elif kind == "google_email":
        allowed = (
            active
            and authoritative
            and evidence == email
            and evidence in policy.allowed_emails
        )
    return bool(allowed and revoked is None), version
