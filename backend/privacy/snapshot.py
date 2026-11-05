"""One bounded consistent snapshot writes unpublished private DB chunks."""

import hashlib
import json
import time
from uuid import uuid4

from preferences.schema import VERSION, validate_values
from privacy import authority, policy, records
from privacy.database import transaction
from privacy.result_fragment import validated_bytes
from workspace.errors import WorkspaceError


class ExportFailure(RuntimeError):
    def __init__(self, code):
        self.code = code


def json_bytes(value):
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode()


class Writer:
    def __init__(self, conn, job, actor, until):
        self.conn, self.job, self.actor, self.until = conn, job, actor, until
        self.pending = bytearray()
        self.total = self.ordinal = 0
        self.digest = hashlib.sha256()

    def check(self):
        if time.monotonic() >= self.until:
            raise ExportFailure("interrupted")

    def flush(self):
        self.check()
        if not self.pending:
            return
        if self.ordinal >= policy.MAX_CHUNKS or not records.lease_current(
            self.conn, self.job, self.actor, self.job["generation"]
        ):
            raise ExportFailure("interrupted")
        body = bytes(self.pending)
        self.conn.execute(
            "INSERT INTO app.data_export_chunks(user_id,job_id,generation,ordinal,body,digest) VALUES(%s,%s,%s,%s,%s,%s)",
            (
                self.job["user_id"],
                self.job["id"],
                self.job["generation"],
                self.ordinal,
                body,
                hashlib.sha256(body).digest(),
            ),
        )
        self.ordinal += 1
        self.pending.clear()

    def write(self, value):
        self.check()
        if (
            type(value) is not bytes
            or self.total + len(value) > policy.MAX_EXPORT_BYTES
        ):
            raise ExportFailure("source_too_large")
        self.total += len(value)
        self.digest.update(value)
        offset = 0
        while offset < len(value):
            take = min(policy.CHUNK_BYTES - len(self.pending), len(value) - offset)
            self.pending.extend(value[offset : offset + take])
            offset += take
            if len(self.pending) == policy.CHUNK_BYTES:
                self.flush()


PROJECTS = "SELECT jsonb_build_object('id',id,'name',name,'archived',archived,'created_at',created_at,'updated_at',updated_at)::text FROM app.projects WHERE user_id=%s AND deleted_at IS NULL ORDER BY id LIMIT %s"
PROMPTS = "SELECT jsonb_build_object('id',id,'label',label,'prompt',prompt,'pinned',pinned,'use_count',use_count,'last_used_at',last_used_at,'created_at',created_at,'updated_at',updated_at)::text FROM app.saved_prompts WHERE user_id=%s AND deleted_at IS NULL ORDER BY id LIMIT %s"
CHATS = "SELECT jsonb_build_object('id',id,'title',title,'project_id',project_id,'archived',archived,'created_at',created_at,'last_activity_at',last_activity_at)::text FROM app.chats WHERE user_id=%s AND deleted_at IS NULL ORDER BY id LIMIT %s"
MESSAGES = """
SELECT jsonb_build_object('id',m.id,'chat_id',m.chat_id,'sequence',m.sequence,'role',m.role,
 'content',CASE WHEN m.role='user' OR (%s AND r.dataset_key=%s) THEN m.content ELSE '' END,
 'status',m.status,'model_id',m.model_id,'created_at',m.created_at,
 'result_unavailable',m.role='aqua' AND NOT (%s AND COALESCE(r.dataset_key=%s,false)))::text,
 CASE WHEN m.role='aqua' AND %s AND r.dataset_key=%s AND v.response IS NOT NULL THEN
 jsonb_build_object('status',v.response->'status','sql',v.response->'sql','model',v.response->'model',
 'message',v.response->'message','tables',v.response->'tables','visualizations',v.response->'visualizations',
 'kpis',v.response->'kpis','error',CASE WHEN jsonb_typeof(v.response->'error')='object' THEN
 jsonb_build_object('code',v.response->'error'->'code','message',v.response->'error'->'message',
 'retryable',v.response->'error'->'retryable') ELSE 'null'::jsonb END)::text ELSE NULL END,
 m.role='aqua' AND %s AND r.dataset_key=%s AND (m.content<>'' OR v.response IS NOT NULL)
FROM app.messages m JOIN app.chats c ON c.user_id=m.user_id AND c.id=m.chat_id AND c.deleted_at IS NULL
LEFT JOIN app.analysis_requests r ON r.user_id=m.user_id AND r.chat_id=m.chat_id AND r.id=m.request_id
LEFT JOIN LATERAL (SELECT response FROM app.visual_results x WHERE x.user_id=m.user_id AND x.chat_id=m.chat_id AND x.request_id=m.request_id ORDER BY revision DESC LIMIT 1) v ON true
WHERE m.user_id=%s ORDER BY m.chat_id,m.sequence,m.id LIMIT %s
"""


def array(writer, query, arguments, maximum, *, messages=False):
    writer.write(b"[")
    count, sensitive = 0, False
    # A named server cursor avoids client-buffering every owned result row.
    with writer.conn.cursor(name="private_export_" + uuid4().hex) as cursor:
        cursor.execute(query, (*arguments, maximum + 1))
        while True:
            writer.check()
            rows = cursor.fetchmany(policy.SNAPSHOT_FETCH_ROWS)
            if not rows:
                break
            for row in rows:
                count += 1
                if count > maximum:
                    raise ExportFailure("source_too_large")
                raw = row[0].encode()
                if messages:
                    response = (
                        validated_bytes(row[1]) if row[1] is not None else b"null"
                    )
                    if not raw.endswith(b"}"):
                        raise ExportFailure("encoding_failed")
                    raw = raw[:-1] + b',"response":' + response + b"}"
                    sensitive = sensitive or bool(row[2])
                if len(raw) > policy.MAX_SOURCE_ROW_BYTES:
                    raise ExportFailure("source_too_large")
                writer.write((b"," if count > 1 else b"") + raw)
    writer.write(b"]")
    return sensitive


def capture(conn, owner, job_id, actor, auth_policy):
    """Own job only; acquire no user/global row locks in this snapshot."""
    until = time.monotonic() + policy.SNAPSHOT_SECONDS
    with transaction(conn, snapshot=True):
        job = records.get(conn, owner, job_id, lock=True)
        if not records.lease_current(conn, job, actor, job["generation"]):
            raise ExportFailure("interrupted")
        try:
            _, allowed, version = authority.check(
                conn, job, auth_policy, results=False, lock=False
            )
        except WorkspaceError:
            raise ExportFailure("authority_changed") from None
        if conn.execute(
            "SELECT count(*) FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s",
            (owner, job_id),
        ).fetchone() != (0,):
            raise ExportFailure("interrupted")
        writer = Writer(conn, job, actor, until)
        instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
        profile = conn.execute(
            "SELECT jsonb_build_object('display_name',u.display_name,'primary_email',e.address,'created_at',u.created_at)::text FROM app.users u JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary AND e.verified_at IS NOT NULL WHERE u.id=%s",
            (owner,),
        ).fetchone()
        if profile is None:
            raise ExportFailure("authority_changed")
        preferences = conn.execute(
            "SELECT schema_version,values FROM app.user_preferences WHERE user_id=%s",
            (owner,),
        ).fetchone() or (VERSION, {})
        if preferences[0] != VERSION:
            raise ExportFailure("encoding_failed")
        values = validate_values(preferences[1], complete=False)
        notifications = conn.execute(
            "SELECT in_app_success,preview FROM app.user_notification_settings WHERE user_id=%s",
            (owner,),
        ).fetchone() or (False, "generic")
        writer.write(b'{"schemaVersion":1,"scope":"personal_v1","export":')
        writer.write(
            json_bytes(
                {
                    "id": str(job["id"]),
                    "created_at": job["created_at"].isoformat(),
                    "snapshot_at": instant.isoformat(),
                    "expires_at": job["expires_at"].isoformat(),
                }
            )
        )
        writer.write(b',"profile":' + profile[0].encode())
        writer.write(
            b',"preferences":'
            + json_bytes({"schemaVersion": VERSION, "values": values})
        )
        writer.write(
            b',"notification_settings":'
            + json_bytes(
                {"in_app_success": notifications[0], "preview": notifications[1]}
            )
        )
        for key, query in [
            ("projects", PROJECTS),
            ("saved_prompts", PROMPTS),
            ("chats", CHATS),
        ]:
            writer.write(b',"' + key.encode() + b'":')
            array(writer, query, (owner,), 1000)
        writer.write(b',"messages":')
        dataset = auth_policy.dataset_key
        contains = array(
            writer,
            MESSAGES,
            (
                allowed,
                dataset,
                allowed,
                dataset,
                allowed,
                dataset,
                allowed,
                dataset,
                owner,
            ),
            20000,
            messages=True,
        )
        writer.write(b"}")
        writer.flush()
        writer.check()
        if not records.lease_current(conn, job, actor, job["generation"]):
            raise ExportFailure("interrupted")
        conn.execute(
            "UPDATE app.data_exports SET output_bytes=%s,chunk_count=%s,contains_results=%s,dataset_key=%s,grant_version=%s WHERE user_id=%s AND id=%s AND generation=%s AND lease_owner=%s",
            (
                writer.total,
                writer.ordinal,
                contains,
                dataset if contains else "",
                version if contains else 0,
                owner,
                job_id,
                job["generation"],
                actor,
            ),
        )
        return {
            "bytes": writer.total,
            "chunks": writer.ordinal,
            "sha256": writer.digest.hexdigest(),
            "generation": job["generation"],
        }
