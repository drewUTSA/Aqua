"""Password session creation rechecks credentials after detached hash work."""

import psycopg

from auth.config import AuthDenied, AuthLimited, AuthPolicy
from auth.password_records import PasswordCandidate
from auth.store import ACTIVE_SESSIONS_SQL
from nl2sql.config import Settings


def create_session(
    conn: psycopg.Connection,
    candidate: PasswordCandidate,
    email: str,
    encoded: str | None,
    token: bytes,
    csrf: bytes,
    auth_policy: AuthPolicy,
    settings: Settings,
) -> None:
    state = conn.execute(
        "SELECT status,auth_epoch FROM app.users WHERE id=%s FOR UPDATE",
        (candidate.owner,),
    ).fetchone()
    current = conn.execute(
        "SELECT p.encoded_hash FROM app.password_credentials p JOIN app.user_emails e ON e.user_id=p.user_id "
        "WHERE p.user_id=%s AND e.email_key=%s AND e.is_primary AND e.verified_at IS NOT NULL",
        (candidate.owner, email),
    ).fetchone()
    if (
        state != ("active", candidate.epoch)
        or current is None
        or current[0] != candidate.encoded
    ):
        raise AuthDenied("password_credentials_invalid")
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    live = conn.execute(
        ACTIVE_SESSIONS_SQL,
        (candidate.owner, candidate.epoch, instant, auth_policy.max_sessions),
    ).fetchall()
    if len(live) >= auth_policy.max_sessions:
        raise AuthLimited(auth_policy.window_seconds)
    if encoded is not None:
        conn.execute(
            "UPDATE app.password_credentials SET encoded_hash=%s,policy_version=1 WHERE user_id=%s",
            (encoded, candidate.owner),
        )
    conn.execute(
        "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) "
        "VALUES (%s,%s,%s,%s,'password',now()+%s*interval '1 second',now()+%s*interval '1 second')",
        (
            candidate.owner,
            token,
            csrf,
            candidate.epoch,
            min(auth_policy.idle_seconds, settings.session_max_age_seconds),
            settings.session_max_age_seconds,
        ),
    )
