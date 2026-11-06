"""Commit the original intent and logical fence before independent publication."""

from datetime import timedelta, timezone

from account.authority import current_id
from account.proof_consumption import consume_proof
from auth.sessions import token_digest
from privacy.database import global_lock
from privacy import deletion_records as records
from retirement import deletion_policy as policy
from retirement.identity_manifest import capture as identity_manifest
from retirement.intents import Intent, MAX_EPOCH
from retirement.original_manifest import encode_original
from retirement.pages import manifest
from workspace.errors import WorkspaceError


def create(service, conn, session, body, ticket, known):
    global_lock(conn)
    permanent, used_bytes = records.control(conn)
    sid = current_id(conn, session, service.policy)
    if not service.capable():
        raise WorkspaceError("service_unavailable", 503)
    # The independent known-intent/absence lookup is held through this commit.
    # A missing visible job does not authorize replaying its original floor.
    if (
        known is not None
        or conn.execute(
            "SELECT 1 FROM app.retirement_intents WHERE installation_id=%s AND intent_id=%s",
            (service.runtime.client.broker.installation, body.intent_id),
        ).fetchone()
        is not None
    ):
        raise WorkspaceError("not_found")
    total, own, live = conn.execute(
        "SELECT count(*),count(*) FILTER(WHERE user_id=%s),count(*) FILTER(WHERE user_id=%s AND state<>'complete') FROM app.deletion_jobs",
        (session.user["id"], session.user["id"]),
    ).fetchone()
    if (
        total >= policy.MAX_JOBS
        or own >= policy.MAX_OWNER_JOBS
        or live
        or permanent >= policy.MAX_PERMANENT_INTENTS
    ):
        raise WorkspaceError("capacity_reached", 429)
    user = conn.execute(
        "SELECT history_generation,privacy_epoch,auth_epoch FROM app.users WHERE id=%s",
        (session.user["id"],),
    ).fetchone()
    closed = body.scope == "account_v1"
    if max(user[:2]) >= MAX_EPOCH or closed and user[2] >= MAX_EPOCH:
        raise WorkspaceError("capacity_reached", 429)
    origin = conn.execute(
        "SELECT absolute_expires_at FROM app.sessions WHERE user_id=%s AND id=%s AND revoked_at IS NULL AND idle_expires_at>clock_timestamp() AND absolute_expires_at>clock_timestamp()",
        (session.user["id"], sid),
    ).fetchone()
    if origin is None:
        raise WorkspaceError("session_invalid", 401)
    client = service.runtime.client
    fingerprints = (
        identity_manifest(
            conn, session.user["id"], client.broker.key, service.policy.dataset_key
        )
        if closed
        else manifest(())
    )
    now = (
        conn.execute("SELECT clock_timestamp()").fetchone()[0].astimezone(timezone.utc)
    )
    if origin[0] <= now:
        raise WorkspaceError("session_invalid", 401)
    job_id = policy.job_identifier(
        service.settings.session_secret,
        client.broker.installation,
        session.user["id"],
        body.intent_id,
        body.scope,
        session.token_digest,
        ticket,
    )
    record = Intent(
        client.broker.installation,
        session.user["id"],
        body.intent_id,
        job_id,
        body.scope,
        now,
        user[0] + 1,
        user[1] + 1,
        user[2] + int(closed),
        closed,
        fingerprint_count=fingerprints.count,
        fingerprint_root=fingerprints.root,
    )
    original = encode_original(record, fingerprints, key_id=client.broker.key.key_id)
    mail_recipients = (
        b"".join(
            bytes(value[0])
            for value in conn.execute(
                "SELECT sha256(convert_to(email_key,'UTF8')) FROM app.user_emails WHERE user_id=%s ORDER BY email_key LIMIT 1001",
                (record.owner,),
            ).fetchall()
        )
        if closed
        else b""
    )
    if len(mail_recipients) > 32000:
        raise WorkspaceError("capacity_reached", 429)
    if (
        len(original) > policy.MAX_MANIFEST_BYTES
        or used_bytes + len(original) > policy.MAX_GLOBAL_MANIFEST_BYTES
    ):
        raise WorkspaceError("capacity_reached", 429)
    # The proof snapshots must still match before the same transaction advances
    # the generations. Failure rolls back proof consumption and every row below.
    consume_proof(
        conn,
        service.policy,
        session,
        policy.operation(body.scope),
        body.intent_id,
        token_digest(body.proof_token),
    )
    conn.execute(
        "UPDATE app.users SET history_generation=%s,privacy_epoch=%s,auth_epoch=%s,status=CASE WHEN %s THEN 'deleting' ELSE status END WHERE id=%s",
        (
            record.history_floor,
            record.privacy_floor,
            record.auth_floor,
            closed,
            record.owner,
        ),
    )
    conn.execute(
        "INSERT INTO app.retirement_intents(installation_id,user_id,intent_id,job_id,scope,created_at,history_floor,privacy_floor,auth_floor,account_closed,fingerprint_count,fingerprint_root) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            record.installation,
            record.owner,
            record.intent,
            record.job,
            record.scope,
            record.created_at,
            record.history_floor,
            record.privacy_floor,
            record.auth_floor,
            closed,
            record.fingerprint_count,
            record.fingerprint_root,
        ),
    )
    conn.execute(
        "INSERT INTO app.deletion_jobs(id,user_id,intent_id,installation_id,scope,created_at,expires_at,receipt_expires_at,origin_absolute_expires_at,origin_session_id,origin_session_digest,receipt_digest,mail_recipients,history_floor,privacy_floor,auth_floor,account_closed,manifest) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (
            record.job,
            record.owner,
            record.intent,
            record.installation,
            record.scope,
            now,
            now + timedelta(seconds=policy.JOB_SECONDS),
            min(now + timedelta(seconds=policy.RECEIPT_SECONDS), origin[0]),
            origin[0],
            sid,
            session.token_digest,
            ticket,
            mail_recipients,
            record.history_floor,
            record.privacy_floor,
            record.auth_floor,
            closed,
            original,
        ),
    )
    conn.execute(
        "UPDATE app.retirement_control SET permanent_intents=permanent_intents+1,manifest_bytes=manifest_bytes+%s WHERE singleton",
        (len(original),),
    )
    return records.get(conn, body.intent_id)
