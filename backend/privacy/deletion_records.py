"""Temporary deletion work and permanent original-intent fences stay distinct."""

from datetime import timezone

from retirement.intents import Intent, reconcile_tombstone
from retirement.interlock import RetirementUnavailable
from retirement.original_manifest import decode_original
from workspace.database import one
from workspace.errors import WorkspaceError


def get(conn, intent_id, *, lock=False):
    return one(
        conn,
        "SELECT j.*,i.fingerprint_count,i.fingerprint_root FROM app.deletion_jobs j JOIN app.retirement_intents i ON i.installation_id=j.installation_id AND i.user_id=j.user_id AND i.intent_id=j.intent_id AND i.job_id=j.id WHERE j.intent_id=%s"
        + (" FOR UPDATE OF j" if lock else ""),
        (intent_id,),
    )


def original(row):
    return Intent(
        str(row["installation_id"]),
        str(row["user_id"]),
        str(row["intent_id"]),
        str(row["id"]),
        row["scope"],
        row["created_at"].astimezone(timezone.utc),
        row["history_floor"],
        row["privacy_floor"],
        row["auth_floor"],
        row["account_closed"],
        fingerprint_count=row["fingerprint_count"],
        fingerprint_root=bytes(row["fingerprint_root"]),
    )


def manifest(row, key_id):
    return decode_original(bytes(row["manifest"]), original(row), key_id=key_id)


def same_original(row, accepted):
    record = accepted.record
    candidate = original(row)
    return (
        record.installation,
        record.owner,
        record.intent,
        record.job,
        record.scope,
        record.created_at,
        record.history_floor,
        record.privacy_floor,
        record.auth_floor,
        record.closed,
        record.fingerprint_count,
        record.fingerprint_root,
    ) == (
        candidate.installation,
        candidate.owner,
        candidate.intent,
        candidate.job,
        candidate.scope,
        candidate.created_at,
        candidate.history_floor,
        candidate.privacy_floor,
        candidate.auth_floor,
        candidate.closed,
        candidate.fingerprint_count,
        candidate.fingerprint_root,
    )


def acknowledge(conn, row, accepted):
    if not same_original(row, accepted):
        raise RetirementUnavailable()
    reconcile_tombstone(conn, accepted.record)
    return one(
        conn,
        "UPDATE app.deletion_jobs SET state=CASE WHEN state='awaiting_authority' THEN 'accepted' ELSE state END,authority_sequence=%s,authority_digest=%s,checkpointed_at=%s WHERE id=%s RETURNING *",
        (
            accepted.record.sequence,
            accepted.record.event_digest,
            accepted.record.checkpointed_at,
            row["id"],
        ),
    )


def control(conn):
    row = conn.execute(
        "SELECT permanent_intents,manifest_bytes FROM app.retirement_control WHERE singleton FOR UPDATE"
    ).fetchone()
    if row is None:
        raise WorkspaceError("service_unavailable", 503)
    return row
