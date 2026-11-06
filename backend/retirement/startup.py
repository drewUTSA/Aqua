"""A restored app cannot claim that its own retirement mirror is complete."""

from dataclasses import replace
from datetime import timezone
import hmac

from retirement.intents import Intent, reconcile_tombstone
from retirement.interlock import RetirementUnavailable


def validate(storage, client, head):
    """Repair only known local pending ACKs; missing history needs recovery role.

    A normal crash may occur after independent acceptance but before the local
    ACK mirror commits. Its exact immutable local intent can be checked and
    filled. An older restore missing intents cannot use this narrow path.
    """
    with storage.transaction() as conn:
        if conn.execute(
            "SELECT recovery_required FROM app.retirement_control WHERE singleton"
        ).fetchone() != (False,):
            raise RetirementUnavailable()
        pending = conn.execute(
            "SELECT installation_id::text,user_id::text,intent_id::text,job_id::text,scope,created_at,history_floor,privacy_floor,auth_floor,account_closed,fingerprint_count,fingerprint_root FROM app.retirement_intents WHERE authority_sequence IS NULL ORDER BY created_at,intent_id LIMIT 129"
        ).fetchall()
    if len(pending) > 128:
        raise RetirementUnavailable()
    for row in pending:
        local = Intent(
            *row[:5],
            row[5].astimezone(timezone.utc),
            *row[6:10],
            fingerprint_count=row[10],
            fingerprint_root=row[11],
        )
        try:
            accepted = client.confirm_acceptance(local.owner, local.intent, local.scope)
        except RetirementUnavailable:
            continue
        known = accepted.record
        if (
            replace(known, sequence=None, event_digest=None, checkpointed_at=None)
            != local
        ):
            raise RetirementUnavailable()
        with storage.transaction() as conn:
            reconcile_tombstone(conn, known)
    with storage.transaction() as conn:
        count, lowest, highest = conn.execute(
            "SELECT count(authority_sequence),min(authority_sequence),max(authority_sequence) FROM app.retirement_intents"
        ).fetchone()
        if (
            count != head.sequence
            or highest != (head.sequence or None)
            or lowest != (1 if count else None)
        ):
            raise RetirementUnavailable()
        if count:
            latest = conn.execute(
                "SELECT event_digest FROM app.retirement_intents WHERE authority_sequence=%s",
                (head.sequence,),
            ).fetchone()
            if latest is None or not hmac.compare_digest(latest[0], head.event_digest):
                raise RetirementUnavailable()
        if (
            conn.execute(
                "SELECT 1 FROM app.users u JOIN (SELECT user_id,max(history_floor) h,max(privacy_floor) p,max(auth_floor) a,bool_or(account_closed) closed FROM app.retirement_intents GROUP BY user_id) r ON r.user_id=u.id WHERE u.history_generation<r.h OR u.privacy_epoch<r.p OR u.auth_epoch<r.a OR (r.closed AND u.status<>'deleting') LIMIT 1"
            ).fetchone()
            is not None
        ):
            raise RetirementUnavailable()
