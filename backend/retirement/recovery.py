"""Offline recovery role only; restored app data cannot attest completeness.

This API never opens credentials or public writers. The operator adapter must
first stop/verify all old backend children. Orphan physical lifetimes remain
blocked until that adapter separately proves actual exit; age is insufficient.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import hmac
import struct
from uuid import UUID

from privacy import deletion_purge
from privacy.database import global_lock
from retirement.checkpoint import ZERO, CheckpointUnavailable
from retirement.intents import Intent, IntentConflict, reconcile_tombstone
from retirement.interlock import LOCK, NAMESPACE, RetirementUnavailable
from retirement.pages import INITIAL, decode, page_digest

DOMAIN = b"AQUA:retirement-event:v1\x00"
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True)
class RecoveryResult:
    events_verified: int
    purge_batches: int
    ready: bool
    pending_manifest: bool = False


def event_digest(record, previous):
    if (
        type(record) is not Intent
        or record.sequence is None
        or type(previous) is not bytes
        or len(previous) != 32
    ):
        raise RetirementUnavailable()
    delta = record.created_at - EPOCH
    micros = delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds
    payload = (
        DOMAIN
        + b"".join(
            UUID(value).bytes
            for value in (record.installation, record.owner, record.intent, record.job)
        )
        + struct.pack(
            "!qBQQQ?I",
            micros,
            2 if record.closed else 1,
            record.history_floor,
            record.privacy_floor,
            record.auth_floor,
            record.closed,
            record.fingerprint_count,
        )
        + record.fingerprint_root
    )
    return hashlib.sha256(
        previous + struct.pack("!q", record.sequence) + payload
    ).digest()


def checked_event(installation, row, previous, sequence):
    try:
        if (
            type(row) is not tuple
            or len(row) != 17
            or row[0] != sequence
            or row[1] != previous
            or row[9] not in {"staging", "sealed"}
        ):
            raise RetirementUnavailable()
        record = Intent(
            installation,
            str(row[4]),
            str(row[3]),
            str(row[5]),
            row[10],
            row[6].astimezone(timezone.utc),
            row[11],
            row[12],
            row[13],
            row[14],
            row[0],
            row[2],
            row[7].astimezone(timezone.utc),
            row[15],
            row[16],
        )
        if not hmac.compare_digest(event_digest(record, previous), record.event_digest):
            raise RetirementUnavailable()
        if (
            (row[9] == "sealed") != (row[8] is not None)
            or row[8] is not None
            and row[8] < record.created_at
        ):
            raise RetirementUnavailable()
        return record, row[9]
    except (ValueError, TypeError, AttributeError, IntentConflict):
        raise RetirementUnavailable() from None


def checked_pages(conn, record, key_id):
    """Stream four128-entry pages at once; never allocate an entire ledger."""
    ordinal, previous, count, last = 0, INITIAL, 0, None
    while True:
        pages = conn.execute(
            "SELECT ordinal,previous_digest,digest,entries FROM retirement.read_pages(%s,%s,4)",
            (record.intent, ordinal - 1),
        ).fetchall()
        if not pages:
            break
        if len(pages) > 4:
            raise RetirementUnavailable()
        for row in pages:
            if (
                type(row) is not tuple
                or len(row) != 4
                or row[0] != ordinal
                or row[1] != previous
            ):
                raise RetirementUnavailable()
            entries = tuple(row[3])
            if len(entries) != min(128, record.fingerprint_count - count):
                raise RetirementUnavailable()
            for value in entries:
                _, fingerprint = decode(value)
                if fingerprint.key_id != key_id or last is not None and value <= last:
                    raise RetirementUnavailable()
                last = value
            previous = page_digest(previous, ordinal, entries)
            if previous != row[2]:
                raise RetirementUnavailable()
            count += len(entries)
            ordinal += 1
        if ordinal > 782:
            raise RetirementUnavailable()
    if count != record.fingerprint_count or previous != record.fingerprint_root:
        raise RetirementUnavailable()


def _reconcile(storage, record):
    with storage.transaction() as app:
        global_lock(app)
        app.execute(
            "SELECT singleton FROM app.retirement_control WHERE singleton FOR UPDATE"
        )
        app.execute("SELECT id FROM app.users WHERE id=%s FOR UPDATE", (record.owner,))
        reconcile_tombstone(app, record)
        app.execute(
            "UPDATE app.users SET history_generation=greatest(history_generation,%s),privacy_epoch=greatest(privacy_epoch,%s),auth_epoch=greatest(auth_epoch,%s),status=CASE WHEN %s THEN 'deleting' ELSE status END WHERE id=%s",
            (
                record.history_floor,
                record.privacy_floor,
                record.auth_floor,
                record.closed,
                record.owner,
            ),
        )


def reconcile(storage, conn, protected, *, purge_guard, batch_limit=128):
    """Recheck full independent history, then clean only original sealed floors.

    The app remains in persistent maintenance on every partial/error path. A
    staging manifest cannot be replaced by an enumeration from an older backup.
    Resume its exact immutable original through the writer, then rerun recovery.
    """
    if (
        type(batch_limit) is not int
        or not 1 <= batch_limit <= 128
        or not conn.autocommit
    ):
        raise RetirementUnavailable()
    if conn.execute(
        "SELECT current_database(),session_user,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=session_user"
    ).fetchone() != (
        "aqua_retirement",
        "aqua_retirement_recovery",
        False,
        False,
        False,
        False,
        False,
        False,
        1,
    ):
        raise RetirementUnavailable()
    with storage.transaction() as app:
        # The existing owner restore-session fence must run before this offline
        # API. Never admit restored cookies merely because their old TTL remains.
        if (
            app.execute(
                "SELECT 1 FROM app.sessions WHERE revoked_at IS NULL LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RetirementUnavailable()
    if conn.execute(
        "SELECT pg_try_advisory_lock(%s,%s)", (NAMESPACE, LOCK)
    ).fetchone() != (True,):
        raise RetirementUnavailable()
    try:
        head = protected.require_current(conn, allow_pending=True, full=True)
        with storage.transaction() as app:
            global_lock(app)
            app.execute(
                "UPDATE app.retirement_control SET recovery_required=true,authority_installed=true WHERE singleton"
            )
            app.execute(
                "UPDATE app.deletion_jobs SET receipt_revoked_at=COALESCE(receipt_revoked_at,clock_timestamp())"
            )
        sequence, previous, pending = 0, ZERO, False
        while True:
            events = conn.execute(
                "SELECT * FROM retirement.read_events(%s,128)", (sequence,)
            ).fetchall()
            if not events:
                break
            if len(events) > 128:
                raise RetirementUnavailable()
            for row in events:
                record, state = checked_event(
                    head.installation, row, previous, sequence + 1
                )
                if state == "sealed":
                    checked_pages(conn, record, head.key_id)
                else:
                    pending = True
                _reconcile(storage, record)
                sequence, previous = record.sequence, record.event_digest
        if (sequence, previous) != (
            head.sequence,
            head.event_digest,
        ) or protected.require_current(conn, allow_pending=True) != head:
            raise RetirementUnavailable()
        if pending:
            return RecoveryResult(sequence, 0, False, True)
        with storage.transaction() as app:
            counted = app.execute(
                "SELECT count(authority_sequence),min(authority_sequence),max(authority_sequence) FROM app.retirement_intents"
            ).fetchone()
            if counted != (
                head.sequence,
                1 if head.sequence else None,
                head.sequence or None,
            ):
                raise RetirementUnavailable()
        batches, after = 0, None
        while True:
            with storage.transaction() as app:
                owners = app.execute(
                    "SELECT user_id::text,max(history_floor),max(privacy_floor),bool_or(account_closed),max(created_at) FROM app.retirement_intents WHERE authority_sequence IS NOT NULL AND (%s::uuid IS NULL OR user_id>%s::uuid) GROUP BY user_id ORDER BY user_id LIMIT 128",
                    (after, after),
                ).fetchall()
            if not owners:
                break
            for owner, history, privacy, closed, created in owners:
                with storage.transaction() as app:
                    mail = b"".join(
                        row[0]
                        for row in app.execute(
                            "SELECT sha256(convert_to(email_key,'UTF8')) FROM app.user_emails WHERE user_id=%s ORDER BY email_key LIMIT 1001",
                            (owner,),
                        ).fetchall()
                    )
                if len(mail) > 32000:
                    raise RetirementUnavailable()
                job = {
                    "user_id": owner,
                    "history_floor": history,
                    "privacy_floor": privacy,
                    "account_closed": closed,
                    "created_at": created,
                    "mail_recipients": mail,
                }
                while batches < batch_limit:
                    with purge_guard(closed) as acquired:
                        if not acquired:
                            return RecoveryResult(sequence, batches, False)
                        with storage.transaction() as app:
                            global_lock(app)
                            app.execute(
                                "SELECT singleton FROM app.retirement_control WHERE singleton FOR UPDATE"
                            )
                            app.execute(
                                "SELECT id FROM app.users WHERE id=%s FOR UPDATE",
                                (owner,),
                            )
                            outcome = deletion_purge.step(app, job)
                            if outcome != "complete":
                                batches += 1
                    if outcome == "complete":
                        break
                    if outcome == "waiting":
                        return RecoveryResult(sequence, batches, False)
                else:
                    return RecoveryResult(sequence, batches, False)
                after = owner
        with storage.transaction() as app:
            global_lock(app)
            app.execute(
                "SELECT singleton FROM app.retirement_control WHERE singleton FOR UPDATE"
            )
            # Exact protected events were checked above. No missing job is
            # interpreted as completion; only actually retained work is settled.
            app.execute(
                "UPDATE app.deletion_jobs j SET state='complete',completed_at=COALESCE(completed_at,clock_timestamp()),manifest='',lease_owner=NULL,lease_until=NULL,authority_sequence=i.authority_sequence,authority_digest=i.event_digest,checkpointed_at=i.checkpointed_at FROM app.retirement_intents i WHERE i.job_id=j.id AND i.intent_id=j.intent_id AND i.authority_sequence IS NOT NULL"
            )
            app.execute(
                "UPDATE app.retirement_control SET permanent_intents=(SELECT count(*) FROM app.retirement_intents),manifest_bytes=(SELECT COALESCE(sum(octet_length(manifest)),0) FROM app.deletion_jobs),recovery_required=false WHERE singleton"
            )
        return RecoveryResult(sequence, batches, True)
    except (CheckpointUnavailable, ValueError, TypeError, IntentConflict):
        raise RetirementUnavailable() from None
    finally:
        if conn.info.transaction_status != 0 or conn.execute(
            "SELECT pg_advisory_unlock(%s,%s)", (NAMESPACE, LOCK)
        ).fetchone() != (True,):
            conn.close()
            raise RetirementUnavailable()
