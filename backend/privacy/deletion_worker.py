"""A real session owns cleanup; signed acceptance alone never authorizes purge."""

import logging
from uuid import uuid4

from privacy import deletion_purge, deletion_records as records
from privacy.database import global_lock, transaction
from retirement.client import ConfirmedAcceptance, ConfirmedRetirement
from retirement.interlock import RetirementUnavailable
from retirement.pages import INITIAL, page_digest
from storage.pool import SCHEMA_VERSION, StorageUnavailable

log = logging.getLogger("aqua.privacy")
WORKER_LOCK = 1095848274


class Worker:
    def __init__(self, service):
        self.service, self.actor = service, uuid4()

    def _lock(self, conn, intent):
        global_lock(conn)
        records.control(conn)
        row = records.get(conn, intent)
        if row is None:
            return None
        conn.execute(
            "SELECT id FROM app.users WHERE id=%s FOR UPDATE", (row["user_id"],)
        )
        return records.get(conn, intent, lock=True)

    def housekeep(self, conn):
        with transaction(conn):
            global_lock(conn)
            records.control(conn)
            # Work is never abandoned merely because its public receipt expired.
            conn.execute(
                "DELETE FROM app.deletion_jobs WHERE id IN (SELECT id FROM app.deletion_jobs WHERE state='complete' AND expires_at<=clock_timestamp() ORDER BY expires_at,id LIMIT 8)"
            )

    def tick(self, conn):
        self.housekeep(conn)
        with transaction(conn):
            global_lock(conn)
            records.control(conn)
            selected = conn.execute(
                "SELECT intent_id::text FROM app.deletion_jobs WHERE state<>'complete' ORDER BY lease_until NULLS FIRST,created_at,id LIMIT 1"
            ).fetchone()
            if selected is None:
                return False
            row = self._lock(conn, selected[0])
            conn.execute(
                "UPDATE app.deletion_jobs SET lease_owner=%s,lease_generation=lease_generation+1,lease_until=clock_timestamp()+interval '15 seconds' WHERE id=%s",
                (self.actor, row["id"]),
            )
        # No application row lock is held across the independent protocol.
        client = self.service.runtime.client
        intent, owner, scope = selected[0], str(row["user_id"]), row["scope"]
        if row["state"] != "purging":
            manifest = records.manifest(row, client.broker.key.key_id)
            pending = client.prepare(records.original(row), manifest)
            accepted = client.confirm_acceptance(owner, intent, scope)
            if type(accepted) is not ConfirmedAcceptance or not records.same_original(
                row, accepted
            ):
                raise RetirementUnavailable()
            with transaction(conn):
                current = self._lock(conn, intent)
                records.acknowledge(conn, current, accepted)
            # Upload at most one fixed page per tick, preserving the immutable
            # original snapshot rather than re-enumerating changing identities.
            if pending.next_page < len(manifest.pages):
                previous = INITIAL
                for ordinal in range(pending.next_page):
                    previous = page_digest(previous, ordinal, manifest.pages[ordinal])
                client.append_page(
                    intent,
                    pending.next_page,
                    previous,
                    manifest.pages[pending.next_page],
                )
                return True
            client.seal(intent)
        confirmed = client.confirm(owner, intent, scope)
        if type(confirmed) is not ConfirmedRetirement or not records.same_original(
            row, confirmed
        ):
            raise RetirementUnavailable()
        with self.service.runtime.purge_guard(row["account_closed"]) as acquired:
            if not acquired:
                return False
            with transaction(conn):
                current = self._lock(conn, intent)
                if current is None or current["state"] == "complete":
                    return True
                records.acknowledge(conn, current, confirmed)
                size = len(current["manifest"])
                if size:
                    conn.execute(
                        "UPDATE app.retirement_control SET manifest_bytes=manifest_bytes-%s WHERE singleton",
                        (size,),
                    )
                conn.execute(
                    "UPDATE app.deletion_jobs SET state='purging',manifest='' WHERE id=%s",
                    (current["id"],),
                )
                outcome = deletion_purge.step(conn, current)
                if outcome == "complete":
                    conn.execute(
                        "UPDATE app.deletion_jobs SET state='complete',completed_at=clock_timestamp(),lease_owner=NULL,lease_until=NULL,purged_batches=purged_batches+1 WHERE id=%s",
                        (current["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE app.deletion_jobs SET purged_batches=purged_batches+1 WHERE id=%s",
                        (current["id"],),
                    )
                return outcome != "waiting"

    def once(self):
        if self.service.pool is None or self.service.stopped.is_set():
            return False
        with self.service.pool.connection() as conn:
            if conn.execute(
                "SELECT pg_try_advisory_lock(%s,%s)", (WORKER_LOCK, 0)
            ).fetchone() != (True,):
                return False
            try:
                if conn.execute(
                    "SELECT max(version) FROM app.schema_migrations"
                ).fetchone() != (SCHEMA_VERSION,):
                    raise StorageUnavailable("privacy_schema_unavailable")
                return self.tick(conn)
            finally:
                conn.execute("SELECT pg_advisory_unlock(%s,%s)", (WORKER_LOCK, 0))

    def loop(self):
        while not self.service.stopped.is_set():
            try:
                if not self.once():
                    self.service.stopped.wait(0.5)
            except (StorageUnavailable, RetirementUnavailable, ValueError, TypeError):
                log.warning("privacy_event action=deletion reason=unavailable")
                self.service.stopped.wait(0.5)
