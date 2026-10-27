"""Bounded metadata SSE rechecks authority; slow clients recover by snapshot."""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from analysis.service import Analysis
import asyncio
import json
import time
from uuid import uuid4
import anyio
from collections.abc import AsyncIterator
from auth.security import UserSession
from starlette.types import Scope, Receive, Send, Message
from fastapi import Request
from starlette.responses import StreamingResponse
from analysis import admission, events, records
from analysis.policy import TERMINAL
from storage.pool import StorageUnavailable
from workspace.errors import WorkspaceError


def inspect(
    service: Analysis,
    session: UserSession,
    request_id: str,
    stream_id: str | None = None,
) -> tuple[dict, list[dict]]:
    with service.storage.transaction() as conn:
        records.authorize(conn, session, service.policy)
        job = records.get(conn, session.user["id"], request_id)
        if not job["request_id"]:
            raise WorkspaceError("not_found")
        # Recheck the parent tombstone even after an already-open connection.
        records.authorize(conn, session, service.policy, job)
        if stream_id:
            updated = conn.execute(
                "UPDATE app.analysis_streams SET expires_at=least(hard_expires_at,clock_timestamp()+interval '5 seconds') WHERE id=%s AND user_id=%s AND expires_at>clock_timestamp() AND hard_expires_at>clock_timestamp() RETURNING id",
                (stream_id, session.user["id"]),
            ).fetchone()
            if updated is None:
                raise WorkspaceError("service_unavailable", 503)
        return job, []


def batch(
    service: Analysis,
    session: UserSession,
    request_id: str,
    stream_id: str,
    sequence: int,
) -> tuple[dict, list[dict]]:
    with service.storage.transaction() as conn:
        records.authorize(conn, session, service.policy)
        job = records.get(conn, session.user["id"], request_id)
        records.authorize(conn, session, service.policy, job)
        updated = conn.execute(
            "UPDATE app.analysis_streams SET expires_at=least(hard_expires_at,clock_timestamp()+interval '5 seconds') WHERE id=%s AND user_id=%s AND expires_at>clock_timestamp() AND hard_expires_at>clock_timestamp() RETURNING id",
            (stream_id, session.user["id"]),
        ).fetchone()
        if updated is None:
            raise WorkspaceError("service_unavailable", 503)
        found = events.after(conn, session.user["id"], request_id, sequence)
        return job, found


def acquire(service: Analysis, session: UserSession, request_id: str) -> str:
    inspect(service, session, request_id)
    with service.storage.transaction() as conn:
        records.authorize(conn, session, service.policy)
        admission.lock(conn)
        conn.execute(
            "DELETE FROM app.analysis_streams WHERE expires_at<=clock_timestamp() OR hard_expires_at<=clock_timestamp()"
        )
        total, own = conn.execute(
            "SELECT count(*),count(*) FILTER(WHERE user_id=%s) FROM app.analysis_streams",
            (session.user["id"],),
        ).fetchone()
        if total >= 8 or own >= 2:
            raise WorkspaceError("analysis_busy", 429)
        stream_id = str(uuid4())
        conn.execute(
            "INSERT INTO app.analysis_streams(id,user_id,request_id,expires_at,hard_expires_at) VALUES(%s,%s,%s,clock_timestamp()+interval '5 seconds',clock_timestamp()+interval '60 seconds')",
            (stream_id, session.user["id"], request_id),
        )
        return stream_id


def release(service: Analysis, stream_id: str) -> None:
    try:
        with service.storage.transaction() as conn:
            conn.execute("DELETE FROM app.analysis_streams WHERE id=%s", (stream_id,))
    except StorageUnavailable:
        # The durable five-second lease remains a fail-closed bounded fallback.
        pass


def frame(kind: str, data: dict) -> bytes:
    data = {
        key: (str(value) if key == "request_id" else value)
        for key, value in data.items()
    }
    encoded = json.dumps(data, separators=(",", ":"))
    if len(encoded) > 512:
        raise ValueError("analysis_event_bound")
    return f"id: {data['request_id']}:{data['sequence']}\nevent: {kind}\ndata: {encoded}\n\n".encode()


class ProgressResponse(StreamingResponse):
    def __init__(
        self, iterator: AsyncIterator[bytes], service: Analysis, stream_id: str
    ) -> None:
        super().__init__(
            iterator,
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )
        self.service, self.stream_id = service, stream_id

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        async def bounded(message: Message) -> None:
            await asyncio.wait_for(send(message), timeout=2)

        try:
            await super().__call__(scope, receive, bounded)
        finally:
            await anyio.to_thread.run_sync(release, self.service, self.stream_id)


def response(
    request: Request, session: UserSession, service: Analysis, request_id: str
) -> ProgressResponse:
    service.observe(session, "read")
    raw = request.headers.get("last-event-id")
    sequence = 0
    if raw is not None:
        try:
            parent, number = raw.rsplit(":", 1)
            sequence = int(number)
            if (
                parent != request_id
                or not 0 <= sequence <= 32
                or str(sequence) != number
                or len(raw) > 80
            ):
                raise ValueError
        except ValueError:
            raise WorkspaceError("invalid_cursor", 422) from None
    stream_id = acquire(service, session, request_id)

    async def iterator() -> AsyncIterator[bytes]:
        nonlocal sequence
        until = time.monotonic() + 60
        try:
            while time.monotonic() < until:
                job, found = await anyio.to_thread.run_sync(
                    batch, service, session, request_id, stream_id, sequence
                )
                missing = sequence > job["last_event_sequence"] or (
                    sequence < job["last_event_sequence"]
                    and (not found or found[0]["sequence"] != sequence + 1)
                )
                if missing:
                    yield frame("snapshot-required", events.public(job))
                    sequence = job["last_event_sequence"]
                else:
                    for item in found:
                        # A replay page is not a single authorization lifetime.
                        # Slow clients must not drain an old authorized batch.
                        await anyio.to_thread.run_sync(
                            inspect, service, session, request_id, stream_id
                        )
                        yield frame("progress", item)
                        sequence = item["sequence"]
                if job["state"] in TERMINAL:
                    break
                yield b": progress heartbeat\n\n"
                await asyncio.sleep(0.8)
        except (WorkspaceError, StorageUnavailable):
            return

    return ProgressResponse(iterator(), service, stream_id)
