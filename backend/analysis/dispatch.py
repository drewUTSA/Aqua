"""Claims are durable; an expired worker may neither commit nor free a live slot."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.service import Analysis
from uuid import uuid4
import logging
from storage.pool import StorageUnavailable
from workspace.errors import WorkspaceError
from analysis import events, records
from analysis.policy import STAGES, TERMINAL

log = logging.getLogger("aqua.analysis")


class Halt(RuntimeError):
    def __init__(self, state: str) -> None:
        self.state = state


class Dispatcher:
    def __init__(self, service: Analysis) -> None:
        self.service = service
        self.owner = str(uuid4())
        from analysis.queue import Queue

        self.queue = Queue(service, self.owner)

    def housekeeping(self) -> None:
        self.queue.housekeeping()

    def claim(self, preferred: str | None = None) -> dict | None:
        return self.queue.claim(preferred)

    def check(self, original: dict, stage: str | None = None) -> None:
        service = self.service
        if service.stopped.is_set():
            raise Halt("interrupted")
        with service.storage.transaction() as conn:
            conn.execute(
                "SELECT id FROM app.users WHERE id=%s FOR UPDATE",
                (original["user_id"],),
            )
            job = records.get(
                conn, str(original["user_id"]), str(original["id"]), lock=True
            )
            current = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            if (
                job["lease_token"] != original["lease_token"]
                or job["lease_owner"] != original["lease_owner"]
                or job["state"] in TERMINAL
            ):
                raise Halt("interrupted")
            if job["cancel_requested"] or job["state"] == "cancelling":
                raise Halt("cancelled")
            if current >= job["deadline_at"]:
                raise Halt("expired")
            if job["lease_until"] is None or current >= job["lease_until"]:
                raise Halt("interrupted")
            try:
                records.authorize(conn, records.identity(job), service.policy, job)
            except WorkspaceError:
                raise Halt("interrupted") from None
            conn.execute(
                "UPDATE app.analysis_jobs SET lease_until=clock_timestamp()+interval '15 seconds' WHERE id=%s",
                (job["id"],),
            )
            if stage is not None:
                if stage not in STAGES or stage in TERMINAL:
                    raise Halt("error")
                events.emit(conn, job, stage)

    def tick(self, preferred: str | None = None) -> bool:
        self.service.storage.readiness()
        self.housekeeping()
        job = self.claim(preferred)
        if job is None:
            return False
        service = self.service
        state = None
        response, status = None, 503
        reaped = True
        release_slot = True
        quarantine = False
        try:
            with service.storage.transaction() as conn:
                question = job["question"]
                if job["request_id"]:
                    question = conn.execute(
                        "SELECT m.content FROM app.analysis_requests r JOIN app.messages m ON m.user_id=r.user_id AND m.id=r.input_message_id WHERE r.id=%s",
                        (job["request_id"],),
                    ).fetchone()[0]
                remaining = float(
                    conn.execute(
                        "SELECT extract(epoch FROM (%s-clock_timestamp()))",
                        (job["deadline_at"],),
                    ).fetchone()[0]
                )
            from analysis.process import payload

            response, status = service.engine.run(
                payload(job, question, service.settings, remaining),
                lambda stage=None: self.check(job, stage),
            )
            self.check(job, "persisting")
        except Halt as error:
            state = error.state
        except Exception as error:
            # Unreaped is the fail-closed exception to confirmed local death.
            # No child/provider/driver exception text crosses this boundary.
            state = "interrupted"
            from analysis.process import Unreaped, RemoteUncertain

            reaped = not isinstance(error, Unreaped)
            quarantine = not reaped
            release_slot = not isinstance(error, (Unreaped, RemoteUncertain))
            if isinstance(error, RemoteUncertain):
                state = error.state
        from analysis.settlement import settle

        settle(service, job, state, reaped, release_slot, quarantine, response, status)
        return True

    def loop(self) -> None:
        while not self.service.stopped.is_set():
            try:
                worked = self.tick()
            except (StorageUnavailable, WorkspaceError):
                worked = False
            if not worked:
                self.service.stopped.wait(0.2)
