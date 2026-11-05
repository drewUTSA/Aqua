"""Actual app/PG send ownership; authored, not locally executed on Windows."""

import asyncio
from copy import copy
from urllib.parse import urlsplit

import anyio
import main

from privacy.database import DOWNLOAD_LOCK, OWNER_DOWNLOAD_LOCK
from privacy.download import Interrupted
from privacy.download import DownloadPool, PHYSICAL, response
from privacy_export_fixture import EXPORTS
from starlette.requests import Request


def test_whole_app_blocked_socket_keeps_physical_locks_until_send_stops(
    private_exports,
):
    fixture = private_exports
    client, owner = fixture.client()
    ready, raw, _ = fixture.ready(client, owner)
    assert ready["byte_count"] == len(raw) and raw
    origin = urlsplit(fixture.world.settings.app_origin)
    path = EXPORTS + "/" + ready["id"] + "/download"
    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": origin.scheme,
        "path": path,
        "raw_path": path.encode(),
        "root_path": "",
        "query_string": b"",
        "server": (origin.hostname, origin.port or 443),
        "client": ("127.0.0.1", 12345),
        "headers": [
            (b"host", origin.netloc.encode()),
            (
                b"cookie",
                "; ".join(
                    name + "=" + value for name, value in client.cookies.items()
                ).encode(),
            ),
            (b"origin", fixture.world.settings.app_origin.encode()),
            (b"x-csrf-token", client.headers["x-csrf-token"].encode()),
            (b"sec-fetch-site", b"same-origin"),
            (b"sec-fetch-mode", b"cors"),
            (b"sec-fetch-dest", b"empty"),
        ],
    }

    async def exercise():
        entered, release, cancelled, stopped = (asyncio.Event() for _ in range(4))
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "http.request", "body": b"", "more_body": False})
        output = []

        async def send(message):
            output.append(message)
            if message["type"] == "http.response.body" and message.get("body"):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
                    await release.wait()
                    stopped.set()

        task = asyncio.create_task(main.app(scope, incoming.get, send))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await asyncio.wait_for(
                cancelled.wait(), 3
            )  # Actual unchanged 2s send deadline.
            assert not task.done() and not stopped.is_set()
            # Read only lock metadata through the existing web pool. No extra
            # downloader pool/slot and no current private row/body is inspected.
            with fixture.world.storage.transaction() as conn:
                locks = conn.execute(
                    "SELECT classid::bigint,pid FROM pg_catalog.pg_locks WHERE locktype='advisory' AND classid::bigint IN (%s,%s) AND granted",
                    (DOWNLOAD_LOCK, OWNER_DOWNLOAD_LOCK),
                ).fetchall()
            assert len(locks) == 2
            assert {row[0] for row in locks} == {DOWNLOAD_LOCK, OWNER_DOWNLOAD_LOCK}
            assert len({row[1] for row in locks}) == 1
            release.set()
            try:
                await task
            except Interrupted:
                pass
            else:
                raise AssertionError(
                    "blocked private attachment completed successfully"
                )
            assert stopped.is_set()
            assert not any(message.get("more_body") is False for message in output)
            assert dict(output[0]["headers"])[b"cache-control"] == b"no-store"
            assert b"cookie" in dict(output[0]["headers"])[b"vary"].lower()
            with fixture.world.storage.transaction() as conn:
                assert conn.execute(
                    "SELECT count(*) FROM pg_catalog.pg_locks WHERE locktype='advisory' AND classid::bigint IN (%s,%s) AND granted",
                    (DOWNLOAD_LOCK, OWNER_DOWNLOAD_LOCK),
                ).fetchone() == (0,)
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            # Pool and all requests close on this same ASGI loop, never through
            # separate TestClient portals. The fixture's later close is idempotent.
            await fixture.service.download_pool.aclose()

    anyio.run(exercise)


def test_terminated_DB_sessions_do_not_release_live_owner_or_global_sends(
    private_exports,
):
    fixture = private_exports
    actors = []
    for label in ("A", "B", "C"):
        client, owner = fixture.client(label)
        ready, _, _ = fixture.ready(client, owner)
        principal = fixture.secure.principal(client)
        origin = urlsplit(fixture.world.settings.app_origin)
        path = EXPORTS + "/" + ready["id"] + "/download"
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": origin.scheme,
            "path": path,
            "raw_path": path.encode(),
            "root_path": "",
            "query_string": b"",
            "server": (origin.hostname, origin.port or 443),
            "client": ("127.0.0.1", 12345),
            "headers": [
                (b"host", origin.netloc.encode()),
                (
                    b"cookie",
                    "; ".join(
                        name + "=" + value for name, value in client.cookies.items()
                    ).encode(),
                ),
                (b"origin", fixture.world.settings.app_origin.encode()),
                (b"x-csrf-token", client.headers["x-csrf-token"].encode()),
                (b"sec-fetch-site", b"same-origin"),
                (b"sec-fetch-mode", b"cors"),
                (b"sec-fetch-dest", b"empty"),
            ],
        }
        actors.append((scope, principal, ready["id"]))

    async def exercise():
        first, second, third = (copy(fixture.service) for _ in range(3))
        second.download_pool = DownloadPool(fixture.world.storage.settings)
        third.download_pool = DownloadPool(fixture.world.storage.settings)
        release = asyncio.Event()
        tasks = []
        entered = [asyncio.Event(), asyncio.Event()]
        stopped = [asyncio.Event(), asyncio.Event()]

        async def request(service, actor, blocking=None):
            scope, principal, job_id = actors[actor]
            incoming = asyncio.Queue()
            incoming.put_nowait(
                {"type": "http.request", "body": b"", "more_body": False}
            )
            output = []

            async def send(message):
                output.append(message)
                if (
                    blocking is not None
                    and message["type"] == "http.response.body"
                    and message.get("body")
                ):
                    entered[blocking].set()
                    try:
                        await asyncio.Event().wait()
                    finally:
                        try:
                            await release.wait()
                        finally:
                            stopped[blocking].set()

            selected = await response(
                Request(scope, incoming.get), principal, service, job_id
            )
            await selected(scope, incoming.get, send)
            return output

        def terminate_download_backend():
            # Runtime can terminate only its own-role DB session. This is a
            # fresh disposable fixture; no host/backend PID enters from a caller.
            with fixture.world.storage.transaction() as conn:
                pids = conn.execute(
                    "SELECT DISTINCT pid FROM pg_catalog.pg_locks WHERE locktype='advisory' AND classid::bigint=%s AND granted",
                    (DOWNLOAD_LOCK,),
                ).fetchall()
                assert len(pids) == 1
                assert conn.execute(
                    "SELECT pg_terminate_backend(%s,1000)", (pids[0][0],)
                ).fetchone() == (True,)

        try:
            tasks.append(asyncio.create_task(request(first, 0, 0)))
            await asyncio.wait_for(entered[0].wait(), 5)
            terminate_download_backend()
            denied_same_pool = await request(first, 0)
            assert denied_same_pool[0]["status"] == 429
            # Independent pool must not reclaim this live owner's physical send.
            denied_owner = await request(second, 0)
            assert denied_owner[0]["status"] == 429
            assert len(PHYSICAL.holders) == 1 and not stopped[0].is_set()
            tasks.append(asyncio.create_task(request(second, 1, 1)))
            await asyncio.wait_for(entered[1].wait(), 5)
            terminate_download_backend()
            with fixture.world.storage.transaction() as conn:
                assert conn.execute(
                    "SELECT count(*) FROM pg_catalog.pg_locks WHERE locktype='advisory' AND classid::bigint IN (%s,%s) AND granted",
                    (DOWNLOAD_LOCK, OWNER_DOWNLOAD_LOCK),
                ).fetchone() == (0,)
            # Both DB owners are gone, but both actual sends remain alive.
            denied_global = await request(third, 2)
            assert denied_global[0]["status"] == 429
            assert len(PHYSICAL.holders) == 2
            assert not any(event.is_set() for event in stopped)
        finally:
            release.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            for service in (first, second, third):
                await service.download_pool.aclose()
            assert not PHYSICAL.holders
            assert all(event.is_set() for event in stopped)

    anyio.run(exercise)
