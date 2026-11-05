"""Owned export admission/status; no provider or filesystem operation exists."""

import logging
import multiprocessing
import os
import sys
import threading

from account.authority import current_id
from account.identity_runtime import admit_action
from account.proof_consumption import consume_proof
from auth.sessions import token_digest
from privacy import authority, policy, records
from privacy.contracts import public_job
from privacy.cursors import Cursors
from privacy.database import PhysicalPool, global_lock
from workspace.database import admit, guard, one, rows
from workspace.errors import WorkspaceError

log = logging.getLogger("aqua.privacy")


class ExportService:
    def __init__(self, storage, auth_policy, settings, *, processes=None, start=False):
        self.storage, self.policy, self.settings = storage, auth_policy, settings
        self.stopped = threading.Event()
        self.thread = None
        self.handles = set()
        self.handles_lock = threading.Lock()
        self.configured = False
        self.worker_pool = self.download_pool = None
        try:
            if processes is None:
                counts = [
                    int(os.environ.get(name, "1"))
                    for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
                ]
                processes = max(counts)
            policy.pool_budget(processes, storage.settings.max_connections)
            self.configured = bool(
                storage.settings.enabled
                and len(settings.session_secret) >= 32
                and policy.activation(
                    os.environ,
                    sys.argv,
                    child=multiprocessing.parent_process() is not None,
                )
            )
            if self.configured:
                from privacy.download import DownloadPool

                self.worker_pool = PhysicalPool(
                    storage.settings, policy.WORKER_POOL_CONNECTIONS
                )
                self.download_pool = DownloadPool(storage.settings)
        except (ValueError, TypeError):
            self.configured = False
            log.warning("privacy_event action=configuration reason=unavailable")
        if start:
            self.start()

    def capable(self, conn):
        return (
            self.configured
            and not self.stopped.is_set()
            and self.download_pool is not None
            and not self.download_pool.closing
            and conn.execute(
                "SELECT max(version) FROM app.schema_migrations"
            ).fetchone()
            == (8,)
        )

    def start(self):
        if self.configured and self.thread is None:
            from privacy.worker import Worker

            self.thread = threading.Thread(
                target=Worker(self).loop, name="aqua-private-export", daemon=True
            )
            self.thread.start()

    def close(self):
        self.stopped.set()
        if self.thread is not None:
            self.thread.join(timeout=5)
        # Never release DB physical slot locks underneath a still-live send or
        # worker snapshot. Its own finally owns release; process death is final.
        if self.thread is None or not self.thread.is_alive():
            if self.worker_pool is not None:
                self.worker_pool.close()

    async def aclose(self):
        import anyio

        await anyio.to_thread.run_sync(self.close)
        if self.download_pool is not None:
            await self.download_pool.aclose()

    def metadata(self, session):
        with self.storage.transaction() as conn:
            guard(conn, session, self.policy)
            admit(conn, session.user["id"])

    def project(self, conn, row, session):
        value = dict(row)
        value["byte_count"] = row["output_bytes"]
        try:
            authority.check(
                conn, row, self.policy, session, results=row["state"] == "ready"
            )
            if (
                row["expires_at"]
                <= conn.execute("SELECT clock_timestamp()").fetchone()[0]
            ):
                raise WorkspaceError("not_found")
        except WorkspaceError:
            value.update(state="expired", error_code=None, sha256=None)
        return public_job(value)

    def envelope(self, conn, row, session):
        return {
            "schemaVersion": 1,
            "user_id": session.user["id"],
            "job": self.project(conn, row, session),
        }

    def create(self, session, body, passwords):
        admit_action(passwords, session)
        with self.storage.transaction() as conn:
            global_lock(conn)
            sid = current_id(conn, session, self.policy)
            if not self.capable(conn):
                raise WorkspaceError("service_unavailable", 503)
            existing = one(
                conn,
                "SELECT * FROM app.data_exports WHERE user_id=%s AND intent_id=%s FOR UPDATE",
                (session.user["id"], body.intent_id),
            )
            if existing is not None:
                return self.envelope(conn, existing, session), 200
            total, own, pending, live, owner_bytes = conn.execute(
                "SELECT count(*),count(*) FILTER(WHERE user_id=%s),count(*) FILTER(WHERE state IN ('queued','working')),count(*) FILTER(WHERE user_id=%s AND state IN ('queued','working','ready')),COALESCE(sum(CASE WHEN reserved_bytes>0 THEN reserved_bytes ELSE output_bytes END) FILTER(WHERE user_id=%s),0) FROM app.data_exports",
                (session.user["id"], session.user["id"], session.user["id"]),
            ).fetchone()
            capacity = conn.execute(
                "SELECT reserved_bytes+stored_bytes FROM app.privacy_control WHERE singleton"
            ).fetchone()[0]
            if (
                total >= policy.MAX_JOB_ROWS
                or own >= policy.MAX_OWNER_JOB_ROWS
                or pending >= policy.MAX_QUEUED_WORKING
                or live
                or owner_bytes + policy.MAX_EXPORT_BYTES > policy.MAX_OWNER_BYTES
                or capacity + policy.MAX_EXPORT_BYTES > policy.MAX_GLOBAL_BYTES
            ):
                raise WorkspaceError("capacity_reached", 429)
            consume_proof(
                conn,
                self.policy,
                session,
                policy.OPERATION,
                body.intent_id,
                token_digest(body.proof_token),
            )
            epoch = authority.privacy_epoch(conn, session.user["id"])
            row = one(
                conn,
                "INSERT INTO app.data_exports(user_id,session_id,intent_id,scope,auth_epoch,privacy_epoch,created_at,expires_at,deadline_at) VALUES(%s,%s,%s,%s,%s,%s,statement_timestamp(),statement_timestamp()+interval '1 hour',statement_timestamp()+interval '120 seconds') RETURNING *",
                (
                    session.user["id"],
                    sid,
                    body.intent_id,
                    body.scope,
                    session.auth_epoch,
                    epoch,
                ),
            )
            conn.execute(
                "UPDATE app.privacy_control SET reserved_bytes=reserved_bytes+%s WHERE singleton",
                (policy.MAX_EXPORT_BYTES,),
            )
            return self.envelope(conn, row, session), 202

    def status(self, session, *, job_id=None, intent_id=None):
        self.metadata(session)
        with self.storage.transaction() as conn:
            guard(conn, session, self.policy)
            if intent_id is not None:
                row = one(
                    conn,
                    "SELECT * FROM app.data_exports WHERE user_id=%s AND intent_id=%s",
                    (session.user["id"], intent_id),
                )
                if row is None:
                    raise WorkspaceError("not_found")
            else:
                row = records.get(conn, session.user["id"], job_id)
            return self.envelope(conn, row, session)

    def listing(self, session, cursor=None):
        self.metadata(session)
        token = Cursors(self.settings.session_secret, session.user["id"])
        position = token.decode(cursor)
        with self.storage.transaction() as conn:
            guard(conn, session, self.policy)
            predicate = ""
            values = [session.user["id"]]
            if position:
                rank, at, item = position
                predicate = " AND (CASE WHEN state IN ('queued','working','ready') THEN 0 ELSE 1 END>%s OR (CASE WHEN state IN ('queued','working','ready') THEN 0 ELSE 1 END=%s AND (created_at,id)<(%s,%s)))"
                values.extend((rank, rank, at, item))
            found = rows(
                conn,
                "SELECT *,CASE WHEN state IN ('queued','working','ready') THEN 0 ELSE 1 END AS rank FROM app.data_exports WHERE user_id=%s"
                + predicate
                + " ORDER BY rank,created_at DESC,id DESC LIMIT 6",
                tuple(values),
            )
            selected = found[: policy.REVIEW_PAGE_SIZE]
            following = (
                token.encode(
                    selected[-1]["rank"], selected[-1]["created_at"], selected[-1]["id"]
                )
                if len(found) > policy.REVIEW_PAGE_SIZE
                else None
            )
            return {
                "schemaVersion": 1,
                "user_id": session.user["id"],
                "jobs": [self.project(conn, row, session) for row in selected],
                "next_cursor": following,
            }
