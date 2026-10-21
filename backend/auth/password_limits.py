"""Shared password budgets and hash slots resist cookie and worker churn."""

from contextlib import contextmanager
from collections.abc import Iterator
import hashlib
import math
import uuid

import psycopg

from auth.config import AuthDenied, AuthLimited
from auth.password_hash import local_slot
from auth.password_policy import PasswordPolicy
from storage.pool import Storage

LOCK = 1095848260


def digest_key(value: str) -> bytes:
    if not isinstance(value, str) or not 1 <= len(value) <= 320:
        raise AuthDenied("password_admission_invalid")
    return hashlib.sha256(value.encode("utf-8")).digest()


def reserve(
    storage: Storage,
    policy: PasswordPolicy,
    operation: str,
    peer: str,
    address: str | None = None,
) -> None:
    if operation not in {"login", "mail", "consume"}:
        raise AuthDenied("password_admission_invalid")
    counters = [
        (
            operation + ":global",
            digest_key("all"),
            getattr(policy, operation + "_global_limit"),
        ),
        (
            operation + ":peer",
            digest_key(peer),
            getattr(policy, operation + "_peer_limit"),
        ),
    ]
    if operation in {"login", "mail"}:
        counters.append(
            (
                operation + ":address",
                digest_key(address),
                getattr(policy, operation + "_address_limit"),
            )
        )
    with storage.transaction() as conn:
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
        now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        conn.execute(
            "DELETE FROM app.password_admission WHERE (scope,key_digest) IN "
            "(SELECT scope,key_digest FROM app.password_admission WHERE expires_at<=%s "
            "ORDER BY expires_at,scope,key_digest LIMIT %s)",
            (now, policy.cleanup_batch),
        )
        count = conn.execute("SELECT count(*) FROM app.password_admission").fetchone()[
            0
        ]
        rows = []
        for scope, key, limit in counters:
            row = conn.execute(
                "SELECT hits,expires_at FROM app.password_admission WHERE scope=%s AND key_digest=%s",
                (scope, key),
            ).fetchone()
            if row and row[1] > now and row[0] >= limit:
                raise AuthLimited(math.ceil((row[1] - now).total_seconds()))
            if row is None:
                count += 1
                if count > policy.max_admission_keys:
                    raise AuthLimited(policy.window_seconds)
            rows.append((scope, key, row))
        for scope, key, row in rows:
            if row is None or row[1] <= now:
                conn.execute(
                    "INSERT INTO app.password_admission(scope,key_digest,hits,expires_at) "
                    "VALUES (%s,%s,1,%s+%s*interval '1 second') ON CONFLICT(scope,key_digest) "
                    "DO UPDATE SET hits=1,expires_at=EXCLUDED.expires_at",
                    (scope, key, now, policy.window_seconds),
                )
            else:
                conn.execute(
                    "UPDATE app.password_admission SET hits=hits+1 WHERE scope=%s AND key_digest=%s",
                    (scope, key),
                )


@contextmanager
def hash_slot(storage: Storage, policy: PasswordPolicy) -> Iterator[None]:
    """Never hold a pool lease during Argon2; retain crash tombstones fail-closed.

    A timer cannot prove a paused worker stopped hashing. Stale slots therefore
    require an operator to stop all auth workers before clearing them; admission
    must not oversubscribe memory merely because a wall-clock lease expired.
    """
    slot = uuid.uuid4()
    with local_slot():
        with storage.transaction() as conn:
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK,))
            if (
                conn.execute("SELECT count(*) FROM app.password_hash_slots").fetchone()[
                    0
                ]
                >= policy.max_hashes
            ):
                raise AuthLimited(1)
            conn.execute("INSERT INTO app.password_hash_slots(id) VALUES (%s)", (slot,))
        try:
            yield
        finally:
            with storage.transaction() as conn:
                conn.execute("DELETE FROM app.password_hash_slots WHERE id=%s", (slot,))


def cleanup_password_challenges(
    conn: psycopg.Connection, policy: PasswordPolicy
) -> None:
    conn.execute(
        "DELETE FROM app.auth_challenges WHERE id IN (SELECT id FROM app.auth_challenges "
        "WHERE purpose IN ('verify_email','password_reset') AND expires_at<=now() "
        "ORDER BY expires_at,id LIMIT %s FOR UPDATE SKIP LOCKED)",
        (policy.cleanup_batch,),
    )
    count = conn.execute(
        "SELECT count(*) FROM app.auth_challenges WHERE purpose IN ('verify_email','password_reset')"
    ).fetchone()[0]
    if count >= policy.max_challenges:
        raise AuthLimited(policy.window_seconds)
