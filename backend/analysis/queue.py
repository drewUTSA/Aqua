"""Durable FIFO claims and bounded retirement never overlap provider work."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.service import Analysis
from workspace.database import one, rows
from workspace.errors import WorkspaceError
from analysis import admission, events, lifecycle, records
from analysis.policy import TERMINAL


class Queue:
    def __init__(self, service: Analysis, owner: str) -> None:
        self.service, self.owner = service, owner

    def housekeeping(self) -> None:
        service = self.service
        with service.storage.transaction() as conn:
            candidates = rows(
                conn,
                "SELECT id,user_id FROM app.analysis_jobs WHERE (state='queued' AND deadline_at<=clock_timestamp()) OR (state IN ('running','cancelling') AND (lease_until<=clock_timestamp() OR deadline_at<=clock_timestamp())) OR (request_id IS NULL AND finished_at<clock_timestamp()-interval '1 hour') ORDER BY created_at LIMIT 20",
            )
        for item in candidates:
            with service.storage.transaction() as conn:
                conn.execute(
                    "SELECT id FROM app.users WHERE id=%s FOR UPDATE",
                    (item["user_id"],),
                )
                admission.lock(conn)
                job = records.get(
                    conn, str(item["user_id"]), str(item["id"]), lock=True
                )
                if job["state"] not in TERMINAL:
                    expired = conn.execute(
                        "SELECT %s<=clock_timestamp()", (job["deadline_at"],)
                    ).fetchone()[0]
                    stale = (
                        job["state"] == "queued"
                        or conn.execute(
                            "SELECT %s<=clock_timestamp()", (job["lease_until"],)
                        ).fetchone()[0]
                    )
                    if expired or stale:
                        lifecycle.terminate(
                            conn, job, "expired" if expired else "interrupted"
                        )
                elif not job["request_id"] and (
                    job["physical_until"] is None
                    or conn.execute(
                        "SELECT %s<=clock_timestamp()", (job["physical_until"],)
                    ).fetchone()[0]
                ):
                    records.purge_input(conn, job)
                    conn.execute(
                        "DELETE FROM app.analysis_jobs WHERE id=%s", (job["id"],)
                    )

    def claim(self, preferred: str | None = None) -> dict | None:
        service = self.service
        with service.storage.transaction() as conn:
            candidates = rows(
                conn,
                "SELECT id,user_id FROM app.analysis_jobs WHERE state='queued'"
                + (" AND id=%s" if preferred else "")
                + " ORDER BY created_at,id LIMIT 10",
                (preferred,) if preferred else (),
            )
        for item in candidates:
            with service.storage.transaction() as conn:
                conn.execute(
                    "SELECT id FROM app.users WHERE id=%s FOR UPDATE",
                    (item["user_id"],),
                )
                job = records.get(
                    conn, str(item["user_id"]), str(item["id"]), lock=True
                )
                if job["state"] != "queued":
                    continue
                try:
                    records.authorize(conn, records.identity(job), service.policy, job)
                except WorkspaceError:
                    lifecycle.terminate(conn, job, "interrupted", reaped=True)
                    continue
                if not admission.has_slot(conn, str(job["user_id"])):
                    continue
                remaining = conn.execute(
                    "SELECT extract(epoch FROM (%s-clock_timestamp()))",
                    (job["deadline_at"],),
                ).fetchone()[0]
                if remaining <= 0:
                    lifecycle.terminate(conn, job, "expired", reaped=True)
                    continue
                job = one(
                    conn,
                    "UPDATE app.analysis_jobs SET lease_token=lease_token+1,lease_owner=%s,lease_until=clock_timestamp()+interval '15 seconds',physical_until=deadline_at+interval '15 seconds',started_at=clock_timestamp() WHERE id=%s RETURNING *",
                    (self.owner, job["id"]),
                )
                return events.emit(conn, job, "context", "running")
        return None
