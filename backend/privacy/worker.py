"""A physical DB session lock, not lease expiry, owns the one privacy worker."""

import logging
from uuid import uuid4

from privacy import authority, policy, records
from privacy.database import WORKER_LOCK, global_lock, transaction
from privacy.snapshot import ExportFailure, capture
from storage.pool import StorageUnavailable
from workspace.database import one, rows
from workspace.errors import WorkspaceError

log = logging.getLogger("aqua.privacy")


class Worker:
    def __init__(self, service):
        self.service, self.actor = service, uuid4()

    def housekeep(self, conn):
        with transaction(conn):
            candidates = rows(
                conn,
                "SELECT id,user_id FROM app.data_exports ORDER BY expires_at,id LIMIT 128",
            )
        changed = 0
        for item in candidates:
            if changed >= 8:
                break
            with transaction(conn):
                global_lock(conn)
                conn.execute(
                    "SELECT id FROM app.users WHERE id=%s FOR UPDATE",
                    (item["user_id"],),
                )
                row = records.get(conn, item["user_id"], item["id"], lock=True)
                instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
                expired = row["expires_at"] <= instant
                invalid = False
                if row["state"] in {"queued", "working", "ready"}:
                    try:
                        authority.check(conn, row, self.service.policy)
                    except WorkspaceError:
                        invalid = True
                if expired or invalid:
                    row = records.expire(conn, row)
                elif row["state"] == "working" and row["lease_until"] <= instant:
                    row = records.expire(conn, row, failure="interrupted")
                elif row["state"] == "queued" and row["deadline_at"] <= instant:
                    row = records.expire(conn, row, failure="interrupted")
                if row["state"] in {"expired", "failed"}:
                    empty = records.cleanup(conn, row)
                    if (
                        empty
                        and row["state"] == "failed"
                        and row["error_code"] == "interrupted"
                        and row["attempts"] < policy.MAX_CLAIMS
                        and row["deadline_at"] > instant
                        and row["expires_at"] > instant
                    ):
                        # Rebuild after a crash only after retiring every old
                        # generation, while the same global lock preserves its
                        # capacity. Recheck authority before reserving again.
                        fresh = records.get(conn, row["user_id"], row["id"], lock=True)
                        try:
                            authority.check(conn, fresh, self.service.policy)
                        except WorkspaceError:
                            pass
                        else:
                            capacity = conn.execute(
                                "SELECT reserved_bytes+stored_bytes FROM app.privacy_control WHERE singleton"
                            ).fetchone()[0]
                            live = conn.execute(
                                "SELECT 1 FROM app.data_exports WHERE user_id=%s AND state IN ('queued','working','ready') LIMIT 1",
                                (row["user_id"],),
                            ).fetchone()
                            pending = conn.execute(
                                "SELECT count(*) FROM app.data_exports WHERE state IN ('queued','working')"
                            ).fetchone()[0]
                            if (
                                live is None
                                and pending < policy.MAX_QUEUED_WORKING
                                and capacity + policy.MAX_EXPORT_BYTES
                                <= policy.MAX_GLOBAL_BYTES
                            ):
                                conn.execute(
                                    "UPDATE app.privacy_control SET reserved_bytes=reserved_bytes+%s WHERE singleton",
                                    (policy.MAX_EXPORT_BYTES,),
                                )
                                conn.execute(
                                    "UPDATE app.data_exports SET state='queued',error_code=NULL,reserved_bytes=%s,contains_results=false,dataset_key='',grant_version=0 WHERE user_id=%s AND id=%s",
                                    (
                                        policy.MAX_EXPORT_BYTES,
                                        row["user_id"],
                                        row["id"],
                                    ),
                                )
                    changed += 1
        return changed

    def claim(self, conn):
        with transaction(conn):
            global_lock(conn)
            active = conn.execute(
                "SELECT worker_job FROM app.privacy_control WHERE singleton AND worker_until>clock_timestamp()"
            ).fetchone()
            if active is not None:
                return None
            candidates = rows(
                conn,
                "SELECT id,user_id FROM app.data_exports WHERE state='queued' AND deadline_at>clock_timestamp() AND expires_at>clock_timestamp() ORDER BY created_at,id LIMIT 4",
            )
            for item in candidates:
                conn.execute(
                    "SELECT id FROM app.users WHERE id=%s FOR UPDATE",
                    (item["user_id"],),
                )
                row = records.get(conn, item["user_id"], item["id"], lock=True)
                try:
                    authority.check(conn, row, self.service.policy)
                except WorkspaceError:
                    records.expire(conn, row, failure="authority_changed")
                    continue
                if row["attempts"] >= policy.MAX_CLAIMS:
                    records.expire(conn, row, failure="interrupted")
                    continue
                # A claimed generation starts empty; partial data never doubles
                # the reservation or becomes a new generation's output.
                if conn.execute(
                    "SELECT count(*) FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s",
                    (row["user_id"], row["id"]),
                ).fetchone() != (0,):
                    records.expire(conn, row, failure="interrupted")
                    continue
                row = one(
                    conn,
                    "UPDATE app.data_exports SET state='working',attempts=attempts+1,generation=generation+1,lease_owner=%s,lease_until=clock_timestamp()+interval '15 seconds' WHERE user_id=%s AND id=%s AND state='queued' RETURNING *",
                    (self.actor, row["user_id"], row["id"]),
                )
                if row is None:
                    continue
                conn.execute(
                    "UPDATE app.privacy_control SET worker_owner=%s,worker_until=clock_timestamp()+interval '15 seconds',worker_job=%s WHERE singleton",
                    (self.actor, row["id"]),
                )
                return row
        return None

    def publish(self, conn, job, prepared):
        with transaction(conn):
            global_lock(conn)
            conn.execute(
                "SELECT id FROM app.users WHERE id=%s FOR UPDATE", (job["user_id"],)
            )
            row = records.get(conn, job["user_id"], job["id"], lock=True)
            if not records.lease_current(conn, row, self.actor, prepared["generation"]):
                raise ExportFailure("interrupted")
            try:
                authority.check(conn, row, self.service.policy)
            except WorkspaceError:
                raise ExportFailure("authority_changed") from None
            count, size = conn.execute(
                "SELECT count(*),COALESCE(sum(octet_length(body)),0) FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s AND generation=%s",
                (row["user_id"], row["id"], row["generation"]),
            ).fetchone()
            if (count, size) != (prepared["chunks"], prepared["bytes"]) or row[
                "reserved_bytes"
            ] != policy.MAX_EXPORT_BYTES:
                raise ExportFailure("encoding_failed")
            conn.execute(
                "UPDATE app.privacy_control SET reserved_bytes=reserved_bytes-%s,stored_bytes=stored_bytes+%s,worker_owner=NULL,worker_until=NULL,worker_job=NULL WHERE singleton",
                (policy.MAX_EXPORT_BYTES, size),
            )
            conn.execute(
                "UPDATE app.data_exports SET state='ready',reserved_bytes=0,sha256=%s,lease_owner=NULL,lease_until=NULL WHERE user_id=%s AND id=%s AND generation=%s AND lease_owner=%s",
                (
                    prepared["sha256"],
                    row["user_id"],
                    row["id"],
                    row["generation"],
                    self.actor,
                ),
            )

    def failed(self, conn, job, code):
        with transaction(conn):
            global_lock(conn)
            conn.execute(
                "SELECT id FROM app.users WHERE id=%s FOR UPDATE", (job["user_id"],)
            )
            row = records.get(conn, job["user_id"], job["id"], lock=True)
            if (
                row["state"] == "working"
                and row["generation"] == job["generation"]
                and row["lease_owner"] == self.actor
            ):
                row = records.expire(conn, row, failure=code)
                records.cleanup(conn, row)

    def tick(self, conn):
        self.housekeep(conn)
        job = self.claim(conn)
        if job is None:
            return False
        try:
            prepared = capture(
                conn, job["user_id"], job["id"], self.actor, self.service.policy
            )
            hook = getattr(self.service, "after_capture", None)
            if hook is not None:
                hook()
            self.publish(conn, job, prepared)
        except ExportFailure as error:
            self.failed(conn, job, error.code)
        except (ValueError, TypeError, RecursionError):
            self.failed(conn, job, "encoding_failed")
        log.info("privacy_event action=export reason=settled")
        return True

    def once(self):
        if not self.service.configured or self.service.stopped.is_set():
            return False
        with self.service.worker_pool.connection() as conn:
            if conn.execute(
                "SELECT pg_try_advisory_lock(%s,%s)", (WORKER_LOCK, 0)
            ).fetchone() != (True,):
                return False
            try:
                if conn.execute(
                    "SELECT max(version) FROM app.schema_migrations"
                ).fetchone() != (8,):
                    raise StorageUnavailable("privacy_schema_unavailable")
                return self.tick(conn)
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s,%s)", (WORKER_LOCK, 0))

    def loop(self):
        while not self.service.stopped.is_set():
            try:
                # Hold physical ownership for this whole worker connection,
                # including idle waits. Lease expiry alone never admits a peer.
                with self.service.worker_pool.connection() as conn:
                    if conn.execute(
                        "SELECT pg_try_advisory_lock(%s,%s)", (WORKER_LOCK, 0)
                    ).fetchone() != (True,):
                        self.service.stopped.wait(0.5)
                        continue
                    try:
                        while not self.service.stopped.is_set():
                            if conn.execute(
                                "SELECT max(version) FROM app.schema_migrations"
                            ).fetchone() != (8,):
                                raise StorageUnavailable("privacy_schema_unavailable")
                            if not self.tick(conn):
                                self.service.stopped.wait(0.5)
                    finally:
                        conn.execute(
                            "SELECT pg_advisory_unlock(%s,%s)", (WORKER_LOCK, 0)
                        )
            except (StorageUnavailable, WorkspaceError):
                log.warning("privacy_event action=worker reason=unavailable")
                self.service.stopped.wait(0.5)
