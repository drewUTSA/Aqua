"""Small durable auth budgets shared by every process, cookie and session."""

import hashlib
import math

import psycopg

from auth.config import AuthDenied, AuthLimited, AuthPolicy

LOCK = 1095848258


def _key(value: str) -> bytes:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise AuthDenied("authentication_identity_invalid")
    return hashlib.sha256(value.encode("utf-8")).digest()


def admit(
    conn: psycopg.Connection,
    policy: AuthPolicy,
    operation: str,
    peer_key: str | None = None,
    account_id: str | None = None,
) -> None:
    """Commit successful admission separately from work that may later fail.

    One short advisory lock serializes only bounded auth bookkeeping. Global
    counters prevent random peer keys from generating unbounded rows. Expired
    rows are removed in batches; a hard key cap denies new keys without evicting
    a currently enforced budget. No external provider call occurs under this lock.
    """
    if operation not in {"challenge", "login", "account", "action"}:
        raise AuthDenied("authentication_operation_invalid")
    counters = []
    if operation in {"challenge", "login"}:
        counters = [
            (
                operation + ":global",
                _key("all"),
                getattr(policy, operation + "_global_limit"),
            ),
            (
                operation + ":peer",
                _key(peer_key),
                getattr(policy, operation + "_peer_limit"),
            ),
        ]
    elif operation == "account":
        counters = [("login:account", _key(account_id), policy.login_account_limit)]
    else:
        counters = [
            ("action:global", _key("all"), policy.action_global_limit),
            ("action:account", _key(account_id), policy.action_account_limit),
        ]
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
    instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    conn.execute(
        "DELETE FROM app.auth_admission WHERE (scope,key_digest) IN "
        "(SELECT scope,key_digest FROM app.auth_admission WHERE expires_at <= %s "
        "ORDER BY expires_at,scope,key_digest LIMIT %s)",
        (instant, policy.cleanup_batch),
    )
    count = conn.execute("SELECT count(*) FROM app.auth_admission").fetchone()[0]
    rows = []
    for scope, key, limit in counters:
        row = conn.execute(
            "SELECT hits,expires_at FROM app.auth_admission WHERE scope=%s AND key_digest=%s",
            (scope, key),
        ).fetchone()
        if row and row[1] > instant and row[0] >= limit:
            raise AuthLimited(math.ceil((row[1] - instant).total_seconds()))
        if row is None:
            count += 1
            if count > policy.max_admission_keys:
                raise AuthLimited(policy.window_seconds)
        rows.append((scope, key, row))
    for scope, key, row in rows:
        # Windows start with the first accepted request; wall-clock rollback
        # lengthens a window instead of issuing a new quota.
        if row is None or row[1] <= instant:
            conn.execute(
                "INSERT INTO app.auth_admission(scope,key_digest,hits,expires_at) "
                "VALUES (%s,%s,1,%s + %s * interval '1 second') "
                "ON CONFLICT(scope,key_digest) DO UPDATE SET hits=1,expires_at=EXCLUDED.expires_at",
                (scope, key, instant, policy.window_seconds),
            )
        else:
            conn.execute(
                "UPDATE app.auth_admission SET hits=hits+1 WHERE scope=%s AND key_digest=%s",
                (scope, key),
            )


def cleanup(conn: psycopg.Connection, policy: AuthPolicy) -> None:
    """Bound deletion work and retain unexpired challenge replay tombstones."""
    mail_exists, requests_exist, exports_exist = conn.execute(
        "SELECT to_regclass('app.account_mail') IS NOT NULL,"
        "to_regclass('app.account_security_requests') IS NOT NULL,"
        "to_regclass('app.data_exports') IS NOT NULL"
    ).fetchone()
    # Login already holds its current user lock. A parent deletion must not
    # cascade into mail rows held by a mail-first sensitive action. That path
    # purges expired jobs first; a later bounded cleanup can retire the ticket.
    retained_mail = (
        "AND NOT EXISTS(SELECT 1 FROM app.account_mail m WHERE m.challenge_id=c.id) "
        if mail_exists
        else ""
    )
    conn.execute(
        "DELETE FROM app.auth_challenges WHERE id IN "
        "(SELECT c.id FROM app.auth_challenges c WHERE c.expires_at <= now() "
        + retained_mail
        + "ORDER BY c.expires_at,c.id LIMIT %s FOR UPDATE OF c SKIP LOCKED)",
        (policy.cleanup_batch,),
    )
    # Schema-7 intents retain an exact session FK independently of their mail
    # challenges. Leave those session rows for the established mail-first
    # bounded request purge; never cascade to encrypted mail under a user lock.
    # The earlier-schema upgrade fixtures must still be cleanable by this code.
    retained_request = (
        "AND NOT EXISTS(SELECT 1 FROM app.account_security_requests r WHERE r.user_id=s.user_id AND r.session_id=s.id) "
        if requests_exist
        else ""
    )
    # A private output keeps its exact originating session until the privacy
    # worker has boundedly retired its chunks/job; never cascade under a user lock.
    retained_export = (
        "AND NOT EXISTS(SELECT 1 FROM app.data_exports e WHERE e.user_id=s.user_id AND e.session_id=s.id) "
        if exports_exist
        else ""
    )
    conn.execute(
        "DELETE FROM app.sessions WHERE id IN "
        "(SELECT s.id FROM app.sessions s WHERE s.absolute_expires_at <= now() "
        "AND NOT EXISTS(SELECT 1 FROM app.auth_challenges c WHERE c.session_id=s.id) "
        + retained_request
        + retained_export
        + "ORDER BY s.absolute_expires_at,s.id LIMIT %s FOR UPDATE OF s SKIP LOCKED)",
        (policy.cleanup_batch,),
    )
