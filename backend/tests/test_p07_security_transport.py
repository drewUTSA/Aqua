"""Real stored session/grant checks bound open metadata replay and consumers."""

import asyncio
import json
import time

import pytest
from starlette.requests import ClientDisconnect, Request

from analysis import streams
from workspace.contracts import FirstSubmission
from workspace.errors import WorkspaceError
from workspace_fixtures import GOOD


def prepared(security, *, complete=False):
    service = security.service()
    _, session = security.session()
    saved, _ = service.enqueue(session, FirstSubmission(**security.world.body()))
    if complete:
        assert service.tick()
    return service, session, saved["request"]["id"]


def request(headers=()):
    return Request(
        {"type": "http", "method": "GET", "path": "/events", "headers": list(headers)}
    )


def test_stream_slots_are_shared_owned_and_never_extend_session_idle(security):
    service, session, ident = prepared(security)
    other = security.service()
    with security.storage.transaction() as conn:
        before = conn.execute(
            "SELECT last_activity_at,idle_expires_at FROM app.sessions WHERE token_digest=%s",
            (session.token_digest,),
        ).fetchone()
    first, second = streams.acquire(service, session, ident), streams.acquire(
        other, session, ident
    )
    try:
        with pytest.raises(WorkspaceError) as denied:
            streams.acquire(other, session, ident)
        assert denied.value.status == 429
        streams.inspect(service, session, ident, first)
        service.snapshot(session, ident)
        with security.storage.transaction() as conn:
            assert (
                conn.execute(
                    "SELECT last_activity_at,idle_expires_at FROM app.sessions WHERE token_digest=%s",
                    (session.token_digest,),
                ).fetchone()
                == before
            )
        _, foreign = security.session("Foreign")
        with pytest.raises(WorkspaceError) as denied:
            streams.acquire(other, foreign, ident)
        assert denied.value.status == 404
    finally:
        streams.release(service, first)
        streams.release(other, second)


@pytest.mark.parametrize(
    "suffix", ["-1", "33", "00", "1.0", "not-an-integer", "1\nforged"]
)
def test_invalid_replay_cursor_allocates_no_stream(security, suffix):
    service, session, ident = prepared(security)
    with pytest.raises(WorkspaceError) as denied:
        streams.response(
            request([(b"last-event-id", f"{ident}:{suffix}".encode())]),
            session,
            service,
            ident,
        )
    assert denied.value.status == 422
    with security.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.analysis_streams").fetchone() == (
            0,
        )


@pytest.mark.parametrize("change", ["session", "grant", "deleted"])
def test_already_open_replay_stops_before_next_frame_after_revocation(security, change):
    service, session, ident = prepared(security, complete=True)
    response = streams.response(request(), session, service, ident)

    async def exercise():
        try:
            first = await asyncio.wait_for(anext(response.body_iterator), timeout=1)
            data = json.loads(
                next(
                    line[6:]
                    for line in first.decode().splitlines()
                    if line.startswith("data: ")
                )
            )
            assert set(data) == {"request_id", "sequence", "version", "state", "stage"}
            assert (
                GOOD["sql"].encode() not in first
                and GOOD["message"].encode() not in first
            )
            with security.storage.transaction() as conn:
                if change == "session":
                    conn.execute(
                        "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE token_digest=%s",
                        (session.token_digest,),
                    )
                elif change == "grant":
                    conn.execute(
                        "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s",
                        (session.user["id"],),
                    )
                else:
                    conn.execute(
                        "UPDATE app.chats SET deleted_at=clock_timestamp() WHERE user_id=%s",
                        (session.user["id"],),
                    )
            with pytest.raises(StopAsyncIteration):
                await asyncio.wait_for(anext(response.body_iterator), timeout=1)
        finally:
            await response.body_iterator.aclose()
            streams.release(service, response.stream_id)

    asyncio.run(exercise())


def test_stalled_asgi_consumer_has_send_deadline_and_releases_durable_slot(security):
    service, session, ident = prepared(security, complete=True)
    response = streams.response(request(), session, service, ident)

    async def exercise():
        async def receive():
            await asyncio.Event().wait()

        async def send(message):
            if message["type"] == "http.response.body":
                await asyncio.Event().wait()

        started = time.monotonic()
        with pytest.raises((TimeoutError, ExceptionGroup, ClientDisconnect)):
            await asyncio.wait_for(
                response(
                    {"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send
                ),
                timeout=3,
            )
        assert time.monotonic() - started < 2.8

    asyncio.run(exercise())
    with security.storage.transaction() as conn:
        assert conn.execute("SELECT count(*) FROM app.analysis_streams").fetchone() == (
            0,
        )
