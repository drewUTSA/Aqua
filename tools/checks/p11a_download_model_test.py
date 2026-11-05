"""Offline async transport/physical-lock model; not a PostgreSQL release proof.

Run directly with the standard library. Driver, ASGI response and PostgreSQL are
explicit models; the actual 2-second send and 60-second total deadlines run.
"""

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import selectors
import sys
import threading
import time
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2] / "backend"
OWNER = "00000000-0000-4000-8000-000000000001"
OTHER = "00000000-0000-4000-8000-000000000002"
JOB = "10000000-0000-4000-8000-000000000001"
SID = "20000000-0000-4000-8000-000000000001"
CURRENT_DB = None


class MemorySelector(selectors.BaseSelector):
    """No I/O occurs in this model; avoid Windows socketpair initialization.

    The sandbox does not provide a loopback socketpair. Timers use real monotonic
    time; register/unregister are deliberately unavailable so no I/O is hidden.
    """

    def register(self, *args, **kwargs):
        raise AssertionError("offline model must not register an I/O descriptor")

    def unregister(self, *args, **kwargs):
        raise AssertionError("offline model must not unregister an I/O descriptor")

    def select(self, timeout=None):
        if timeout:
            time.sleep(timeout)
        return []

    def get_map(self):
        return {}


class MemoryLoop(asyncio.SelectorEventLoop):
    def __init__(self):
        super().__init__(selector=MemorySelector())

    def _make_self_pipe(self):
        pass

    def _close_self_pipe(self):
        pass

    def _write_to_self(self):
        # All model work is on this one thread, never from a worker callback.
        pass


@dataclass
class WorkspaceError(Exception):
    code: str
    status: int = 404


class DriverError(Exception):
    pass


class StorageUnavailable(RuntimeError):
    pass


class JsonFailure:
    def __init__(self, error):
        self.error = error

    async def __call__(self, scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": self.error.status,
                "headers": [(b"cache-control", b"no-store")],
            }
        )
        await send(
            {
                "type": "http.response.body",
                "body": json.dumps({"error": {"code": self.error.code}}).encode(),
                "more_body": False,
            }
        )


class StreamBase:
    def __init__(self, *args, **kwargs):
        pass


def load_module():
    def module(name, **items):
        result = ModuleType(name)
        result.__dict__.update(items)
        return result

    spec = importlib.util.spec_from_file_location(
        "draft_download_policy", ROOT / "privacy" / "policy.py"
    )
    policy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(policy)
    modules = {
        "privacy": module("privacy", policy=policy),
        "privacy.policy": policy,
        "privacy.database": module(
            "privacy.database", DOWNLOAD_LOCK=1095848271, OWNER_DOWNLOAD_LOCK=1095848272
        ),
        "storage": module("storage"),
        "storage.pool": module("storage.pool", StorageUnavailable=StorageUnavailable),
        "workspace": module("workspace"),
        "workspace.errors": module(
            "workspace.errors", WorkspaceError=WorkspaceError, failure=JsonFailure
        ),
        "psycopg": module("psycopg", Error=DriverError),
        "psycopg.rows": module("psycopg.rows", dict_row=object(), tuple_row=object()),
        "psycopg_pool": module(
            "psycopg_pool",
            AsyncConnectionPool=ModelPool,
            PoolClosed=DriverError,
            PoolTimeout=DriverError,
            TooManyRequests=DriverError,
        ),
        "starlette": module("starlette"),
        "starlette.responses": module(
            "starlette.responses", StreamingResponse=StreamBase
        ),
    }
    spec = importlib.util.spec_from_file_location(
        "draft_private_download", ROOT / "privacy" / "download.py"
    )
    result = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, modules):
        spec.loader.exec_module(result)
    return result


class ModelTransaction:
    def __init__(self, conn):
        self.conn = conn

    async def __aenter__(self):
        if self.conn.in_transaction:
            raise AssertionError("nested transaction")
        self.conn.in_transaction = True
        self.saved = dict(self.conn.db.admission)
        self.conn.db.events.append((self.conn, "begin"))

    async def __aexit__(self, kind, value, trace):
        self.conn.db.events.append(
            (self.conn, "commit" if kind is None else "rollback")
        )
        self.conn.in_transaction = False
        if kind is not None:
            self.conn.db.admission = self.saved


class ModelCursor:
    def __init__(self, conn):
        self.conn = conn
        self.row = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def execute(self, query, values=()):
        self.row = await self.conn.db.execute(self.conn, query, values)

    async def fetchone(self):
        return self.row


class ModelConnection:
    def __init__(self, db):
        self.db = db
        self.in_transaction = self.closed = False
        db.connections.append(self)

    def cursor(self, **kwargs):
        return ModelCursor(self)

    def transaction(self):
        return ModelTransaction(self)

    async def close(self):
        self.closed = True
        self.db.release(self)
        self.db.events.append((self, "close"))


class ModelPool:
    def __init__(self, dsn, **kwargs):
        self.db = CURRENT_DB
        self.options = kwargs
        self.capacity = asyncio.Semaphore(kwargs["max_size"])
        self.checked_out = set()
        self.closed = False
        self.opened = self.acquisitions = 0

    @staticmethod
    async def check_connection(conn):
        pass

    async def open(self, **kwargs):
        self.opened += 1

    async def getconn(self, **kwargs):
        if self.closed:
            raise DriverError("MODEL_PRIVATE_DRIVER")
        try:
            async with asyncio.timeout(kwargs["timeout"]):
                await self.capacity.acquire()
        except TimeoutError:
            raise DriverError("MODEL_PRIVATE_DRIVER") from None
        conn = ModelConnection(self.db)
        self.checked_out.add(conn)
        self.acquisitions += 1
        return conn

    async def putconn(self, conn):
        if conn not in self.checked_out:
            raise AssertionError("double return")
        self.checked_out.remove(conn)
        self.capacity.release()

    async def close(self, **kwargs):
        self.closed = True
        self.db.events.append((self, "pool_close"))


class ModelDatabase:
    def __init__(self):
        self.now = datetime(2026, 10, 31, tzinfo=timezone.utc)
        self.connections = []
        self.events = []
        self.queries = []
        self.admission = {}
        self.locks = {}
        self.users = {}
        self.sessions = {}
        self.grants = {}
        self.jobs = {}
        self.chunks = {}
        self.reset_failure = False
        self.lock_pause = None
        self.lock_acquired = asyncio.Event()
        self.schema = 8

    def add(self, owner=OWNER, body=None, *, results=True):
        body = body if body is not None else b"a" * (65536 + 13)
        self.users[owner] = ("active", 3, 7)
        self.sessions[owner] = (SID, True)
        self.grants[owner] = (11, None, "operator", None, None, None, None, None)
        self.jobs[owner, JOB] = {
            "id": JOB,
            "user_id": owner,
            "session_id": SID,
            "auth_epoch": 3,
            "privacy_epoch": 7,
            "scope": "personal_v1",
            "state": "ready",
            "created_at": self.now,
            "expires_at": self.now + timedelta(hours=1),
            "generation": 2,
            "chunk_count": (len(body) + 65535) // 65536,
            "output_bytes": len(body),
            "sha256": hashlib.sha256(body).hexdigest(),
            "contains_results": results,
            "dataset_key": "fixture",
            "grant_version": 11,
        }
        for ordinal, start in enumerate(range(0, len(body), 65536)):
            chunk = body[start : start + 65536]
            self.chunks[owner, JOB, 2, ordinal] = (
                chunk,
                hashlib.sha256(chunk).digest(),
            )
        return body

    def release(self, conn):
        self.locks = {
            key: holder for key, holder in self.locks.items() if holder is not conn
        }

    async def execute(self, conn, query, values):
        if conn.closed:
            raise DriverError("MODEL_PRIVATE_DRIVER")
        self.queries.append((conn, query, values))
        if query.startswith("SET "):
            return None
        if query == "DISCARD ALL":
            if self.reset_failure:
                raise DriverError("MODEL_PRIVATE_DRIVER")
            self.release(conn)
            self.events.append((conn, "released"))
            return None
        if query.startswith("SELECT current_database()"):
            return "aqua_app", "aqua_app_runtime", False
        if query.startswith("SELECT NOT EXISTS"):
            return (not any(holder is conn for holder in self.locks.values()),)
        if query.startswith("SELECT max(version)"):
            return (self.schema,)
        if query.startswith("SELECT singleton"):
            return (True,)
        if query.startswith("SELECT status,auth_epoch"):
            return self.users.get(values[0])
        if query.startswith("SELECT id FROM app.sessions"):
            item = self.sessions.get(values[0])
            return (item[0],) if item and item[1] else None
        if query == "SELECT clock_timestamp()":
            return (self.now,)
        if query.startswith("DELETE FROM app.privacy_admission"):
            self.admission = {
                key: item for key, item in self.admission.items() if item[1] > values[0]
            }
            return None
        if query.startswith("SELECT count(*) FROM app.privacy_admission"):
            return (len(self.admission),)
        if query.startswith("SELECT hits,expires_at"):
            return self.admission.get(tuple(values))
        if query.startswith("INSERT INTO app.privacy_admission"):
            scope, key, instant, _, _ = values
            old = self.admission.get((scope, key))
            self.admission[scope, key] = (
                (old[0] + 1, old[1])
                if old and old[1] > instant
                else (1, instant + timedelta(minutes=1))
            )
            return None
        if query.startswith("SELECT pg_try_advisory_lock"):
            key = tuple(values)
            if key in self.locks and self.locks[key] is not conn:
                return (False,)
            self.locks[key] = conn
            if self.lock_pause is not None:
                pause, self.lock_pause = self.lock_pause, None
                self.lock_acquired.set()
                await pause.wait()
            return (True,)
        if query.startswith("SELECT pg_advisory_unlock"):
            key = tuple(values)
            if self.locks.get(key) is not conn:
                return (False,)
            del self.locks[key]
            return (True,)
        if query.startswith("SELECT * FROM app.data_exports"):
            item = self.jobs.get(tuple(values))
            return dict(item) if item else None
        if query.startswith("SELECT g.version"):
            return self.grants.get(values[0])
        if query.startswith("SELECT body,digest"):
            return self.chunks.get(tuple(values))
        raise AssertionError("unrecognized fixed query: " + query)


download = load_module()


class ModelRequest:
    def __init__(self, *, csrf="fixture-csrf", extra=(), method="GET", query=b""):
        self.scope = {
            "method": method,
            "query_string": query,
            "headers": [(b"x-csrf-token", csrf.encode()), *extra],
        }
        self.incoming = asyncio.Queue()
        self.incoming.put_nowait(
            {"type": "http.request", "body": b"", "more_body": False}
        )
        self.receive = self.incoming.get


class DownloadTests(unittest.IsolatedAsyncioTestCase):
    def _setupAsyncioRunner(self):
        self._asyncioRunner = asyncio.Runner(
            debug=True,
            loop_factory=MemoryLoop if os.name == "nt" else asyncio.new_event_loop,
        )

    def setUp(self):
        self.services = []
        self.tasks = []
        self.new_world()

    def new_world(self):
        # Separate synthetic worlds, with unchanged production attempt limits.
        global CURRENT_DB
        self.db = CURRENT_DB = ModelDatabase()
        self.body = self.db.add()

    def service(self):
        value = SimpleNamespace(
            configured=True,
            stopped=threading.Event(),
            settings=SimpleNamespace(app_origin="https://fixture.invalid"),
            policy=SimpleNamespace(
                dataset_key="fixture",
                allowed_google_subs=frozenset({"allowed-sub"}),
                allowed_emails=frozenset({"allowed@example.invalid"}),
            ),
            download_pool=download.DownloadPool(SimpleNamespace(dsn="MODEL_DSN")),
        )
        self.services.append(value)
        return value

    def session(self, owner=OWNER):
        return SimpleNamespace(
            user={"id": owner},
            csrf_token="fixture-csrf",
            token_digest=b"fixture-session",
            auth_epoch=3,
        )

    async def run_response(
        self, service=None, *, owner=OWNER, request=None, job=JOB, callback=None
    ):
        service = service or self.service()
        request = request or ModelRequest()
        output = []

        async def send(message):
            self.assertFalse(
                any(conn.in_transaction for conn in self.db.connections),
                "network send under DB transaction",
            )
            output.append(message)
            if callback:
                await callback(message)

        response = await download.response(request, self.session(owner), service, job)
        await response(request.scope, request.receive, send)
        return output

    async def start_blocked(self, service, owner=OWNER, *, cancel_gate=None):
        entered = asyncio.Event()
        release = asyncio.Event()
        stopped = asyncio.Event()

        async def callback(message):
            if message["type"] == "http.response.body" and message.get("body"):
                entered.set()
                try:
                    await release.wait()
                finally:
                    if cancel_gate is not None:
                        await cancel_gate.wait()
                    stopped.set()

        task = asyncio.create_task(
            self.run_response(service, owner=owner, callback=callback)
        )
        self.tasks.append(task)
        await asyncio.wait_for(entered.wait(), 1)
        return task, release, stopped

    async def asyncTearDown(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        for service in self.services:
            await service.download_pool.aclose()
            self.assertEqual(service.download_pool.pool.db.locks, {})
        self.assertTrue(
            all(
                not service.download_pool.active
                and not service.download_pool.pool.checked_out
                for service in self.services
            )
        )
        self.assertEqual(download.PHYSICAL.holders, {})

    def test_pool_and_deadlines_are_fixed(self):
        service = self.service()
        options = service.download_pool.pool.options
        self.assertEqual(
            (
                options["min_size"],
                options["max_size"],
                options["max_waiting"],
                options["timeout"],
                options["num_workers"],
            ),
            (0, 2, 1, 1, 1),
        )
        self.assertEqual(
            options["kwargs"],
            {"autocommit": True, "prepare_threshold": None, "connect_timeout": 2},
        )
        self.assertEqual(
            (
                download.policy.DOWNLOAD_SECONDS,
                download.policy.ASGI_SEND_SECONDS,
                download.policy.CHUNK_BYTES,
            ),
            (60, 2, 65536),
        )
        self.assertEqual(download.policy.pool_budget(1, 4), 8)
        with self.assertRaises(ValueError):
            download.policy.pool_budget(2, 4)

    async def test_transport_denies_before_any_sql_or_pool_open(self):
        service = self.service()
        cases = [
            {"csrf": "wrong"},
            {"extra": [(b"x-csrf-token", b"fixture-csrf")]},
            {"extra": [(b"origin", b"https://foreign.invalid")]},
            {"extra": [(b"sec-fetch-site", b"cross-site")]},
            {"extra": [(b"sec-fetch-mode", b"navigate")]},
            {"extra": [(b"sec-fetch-dest", b"document")]},
            {"extra": [(b"range", b"bytes=0-4")]},
            {"extra": [(b"if-range", b"x")]},
            {"extra": [(b"purpose", b"prefetch")]},
            {"extra": [(b"transfer-encoding", b"chunked")]},
            {"extra": [(b"content-length", b"1")]},
            {"query": b"token=private"},
            {"method": "POST"},
        ]
        for case in cases:
            with self.subTest(case=case), self.assertRaises(WorkspaceError):
                await download.response(
                    ModelRequest(**case), self.session(), service, JOB
                )
        self.assertEqual(self.db.queries, [])
        self.assertEqual(service.download_pool.pool.opened, 0)

    async def test_uncalled_response_holds_no_connection(self):
        service = self.service()
        await download.response(ModelRequest(), self.session(), service, JOB)
        self.assertEqual(self.db.queries, [])
        self.assertEqual(service.download_pool.active, set())

    async def test_nonempty_actual_body_denied_before_sql(self):
        request = ModelRequest()
        request.incoming.get_nowait()
        request.incoming.put_nowait({"type": "http.request", "body": b"PRIVATE_BODY"})
        output = await self.run_response(request=request)
        self.assertEqual(output[0]["status"], 422)
        self.assertEqual(self.db.queries, [])

    async def test_success_rechecks_every_chunk_and_sends_exact_opaque_bytes(self):
        output = await self.run_response()
        self.assertEqual(output[0]["status"], 200)
        self.assertEqual(b"".join(item.get("body", b"") for item in output), self.body)
        headers = dict(output[0]["headers"])
        self.assertEqual(
            headers[b"content-disposition"],
            b'attachment; filename="aqua-personal-data-v1.json"',
        )
        self.assertEqual(headers[b"cache-control"], b"private, no-store")
        self.assertEqual(headers[b"x-content-type-options"], b"nosniff")
        self.assertFalse(output[-1]["more_body"])
        queries = [query for _, query, _ in self.db.queries]
        self.assertEqual(
            sum(query.startswith("SELECT g.version") for query in queries), 3
        )
        job_index = next(
            i
            for i, query in enumerate(queries)
            if query.startswith("SELECT * FROM app.data_exports")
        )
        self.assertTrue(any(event == "commit" for _, event in self.db.events))
        self.assertLess(
            next(
                i
                for i, query in enumerate(queries)
                if query.startswith("INSERT INTO app.privacy_admission")
            ),
            job_index,
        )
        self.assertEqual(sorted(item[0] for item in self.db.admission.values()), [1, 1])

    async def test_owned_lookup_failures_spend_durable_admission_and_cap_at_five(self):
        service = self.service()
        for attempt in range(6):
            output = await self.run_response(service, job=OTHER)
            self.assertEqual(output[0]["status"], 404 if attempt < 5 else 429)
        self.assertEqual(sorted(item[0] for item in self.db.admission.values()), [5, 5])
        self.assertEqual(self.db.locks, {})

    async def test_foreign_job_and_other_origin_session_are_not_downloadable(self):
        self.db.add(OTHER)
        self.db.jobs.pop((OWNER, JOB))
        self.assertEqual((await self.run_response())[0]["status"], 404)
        self.db.add(OWNER)
        self.db.sessions[OWNER] = (OTHER, True)
        self.assertEqual((await self.run_response())[0]["status"], 404)

    async def test_privacy_auth_and_grant_changes_stop_remaining_bytes(self):
        mutations = [
            lambda: self.db.users.update({OWNER: ("active", 3, 8)}),
            lambda: self.db.users.update({OWNER: ("active", 4, 7)}),
            lambda: self.db.sessions.update({OWNER: (SID, False)}),
            lambda: self.db.grants.update(
                {OWNER: (12, None, "operator", None, None, None, None, None)}
            ),
            lambda: self.db.grants.update(
                {OWNER: (11, self.db.now, "operator", None, None, None, None, None)}
            ),
            lambda: self.db.grants.update(
                {
                    OWNER: (
                        11,
                        None,
                        "google_subject",
                        "allowed-sub",
                        "allowed-sub",
                        None,
                        False,
                        False,
                    )
                }
            ),
        ]
        for mutate in mutations:
            self.new_world()
            output = []

            async def callback(message):
                output.append(message)
                if message["type"] == "http.response.body" and message.get("body"):
                    mutate()

            with self.subTest(mutation=mutate), self.assertRaises(download.Interrupted):
                await self.run_response(callback=callback)
            self.assertEqual(sum(len(item.get("body", b"")) for item in output), 65536)
            self.assertFalse(any(item.get("more_body") is False for item in output))
            self.assertEqual(self.db.locks, {})

    async def test_headers_backpressure_cannot_bypass_before_first_byte_check(self):
        output = []

        async def callback(message):
            output.append(message)
            if message["type"] == "http.response.start":
                self.db.users[OWNER] = ("active", 3, 8)

        with self.assertRaises(download.Interrupted):
            await self.run_response(callback=callback)
        self.assertEqual(len(output), 1)

    async def test_no_results_export_does_not_gain_data_on_new_grant(self):
        self.db.add(body=b'{"personal":"only"}', results=False)
        self.db.grants[OWNER] = (55, None, "operator", None, None, None, None, None)
        output = await self.run_response()
        self.assertEqual(
            b"".join(item.get("body", b"") for item in output), b'{"personal":"only"}'
        )

    async def test_metadata_generation_size_scope_and_expiry_cannot_change(self):
        for field, value in [
            ("scope", "all_users"),
            ("generation", 0),
            ("chunk_count", 999),
            ("output_bytes", True),
            ("expires_at", self.db.now),
            ("expires_at", self.db.now + timedelta(hours=2)),
        ]:
            self.new_world()
            self.db.jobs[OWNER, JOB][field] = value
            output = await self.run_response()
            self.assertIn(output[0]["status"], (404, 503))
            self.assertNotEqual(output[0]["status"], 200)
        self.new_world()
        self.db.schema = 9
        self.assertEqual((await self.run_response())[0]["status"], 503)

    async def test_chunk_corruption_and_whole_hash_mismatch_never_finish_attachment(
        self,
    ):
        self.db.chunks[OWNER, JOB, 2, 0] = (b"x" * 65536, b"x" * 32)
        self.assertEqual((await self.run_response())[0]["status"], 503)
        self.db.add()
        self.db.jobs[OWNER, JOB]["sha256"] = "0" * 64
        output = []

        async def callback(message):
            output.append(message)

        with self.assertRaises(download.Interrupted):
            await self.run_response(callback=callback)
        self.assertFalse(any(item.get("more_body") is False for item in output))
        self.assertEqual(sum(len(item.get("body", b"")) for item in output), 65536)

    async def test_two_global_slots_and_one_owner_hold_across_separate_pools(self):
        self.db.add(OTHER)
        third = str(UUID(int=3))
        self.db.add(third)
        first_service, second_service, third_service = (
            self.service(),
            self.service(),
            self.service(),
        )
        first, release_first, _ = await self.start_blocked(first_service)
        self.assertEqual((await self.run_response(second_service))[0]["status"], 429)
        self.assertEqual(len(self.db.locks), 2)
        second, release_second, _ = await self.start_blocked(second_service, OTHER)
        self.assertEqual(len(self.db.locks), 4)
        self.assertEqual(
            (await self.run_response(third_service, owner=third))[0]["status"], 429
        )
        release_first.set()
        await first
        self.assertEqual(
            (await self.run_response(third_service, owner=third))[0]["status"], 200
        )
        release_second.set()
        await second

    async def test_lost_DB_sessions_cannot_reclaim_owner_or_global_physical_slots(self):
        self.db.add(OTHER)
        third = str(UUID(int=3))
        self.db.add(third)
        first_service, second_service, third_service = (
            self.service(),
            self.service(),
            self.service(),
        )
        first, release_first, _ = await self.start_blocked(first_service)
        lost = next(iter(first_service.download_pool.pool.checked_out))
        self.db.release(lost)
        lost.closed = True  # Model pg_terminate_backend while actual send lives.
        self.assertEqual(self.db.locks, {})
        self.assertEqual((await self.run_response(second_service))[0]["status"], 429)
        self.assertEqual(second_service.download_pool.pool.acquisitions, 0)
        second, release_second, _ = await self.start_blocked(second_service, OTHER)
        lost_other = next(iter(second_service.download_pool.pool.checked_out))
        self.db.release(lost_other)
        lost_other.closed = True
        self.assertEqual(self.db.locks, {})
        self.assertEqual(
            (await self.run_response(third_service, owner=third))[0]["status"], 429
        )
        self.assertEqual(third_service.download_pool.pool.acquisitions, 0)
        self.assertEqual(len(download.PHYSICAL.holders), 2)
        release_first.set()
        release_second.set()
        results = await asyncio.gather(first, second, return_exceptions=True)
        self.assertTrue(
            all(isinstance(result, download.Interrupted) for result in results)
        )
        self.assertEqual(download.PHYSICAL.holders, {})

    async def test_real_send_deadline_keeps_lock_until_cancelled_send_actually_stops(
        self,
    ):
        gate = asyncio.Event()
        service = self.service()
        task, _, stopped = await self.start_blocked(service, cancel_gate=gate)
        await asyncio.sleep(2.1)
        self.assertFalse(stopped.is_set())
        self.assertFalse(task.done())
        self.assertEqual(len(self.db.locks), 2)
        self.assertEqual((await self.run_response(self.service()))[0]["status"], 429)
        gate.set()
        with self.assertRaises(download.Interrupted):
            await task
        self.assertTrue(stopped.is_set())
        self.assertEqual(self.db.locks, {})

    async def test_disconnect_and_service_shutdown_drain_before_pool_close(self):
        service = self.service()
        request = ModelRequest()
        entered, stopped = asyncio.Event(), asyncio.Event()

        async def blocked(message):
            if message["type"] == "http.response.body" and message.get("body"):
                entered.set()
                try:
                    await asyncio.Event().wait()
                finally:
                    stopped.set()

        task = asyncio.create_task(
            self.run_response(service, request=request, callback=blocked)
        )
        self.tasks.append(task)
        await entered.wait()
        request.incoming.put_nowait({"type": "http.disconnect"})
        await task
        self.assertTrue(stopped.is_set())
        self.assertFalse(service.download_pool.pool.closed)
        other, _, other_stopped = await self.start_blocked(service)
        await service.download_pool.aclose()
        self.assertTrue(other_stopped.is_set())
        self.assertTrue(other.done())
        self.assertTrue(service.download_pool.pool.closed)
        self.assertEqual(service.download_pool.active, set())

    async def test_cancel_during_advisory_acquisition_releases_exact_session(self):
        service = self.service()
        self.db.lock_pause = asyncio.Event()
        task = asyncio.create_task(self.run_response(service))
        self.tasks.append(task)
        await self.db.lock_acquired.wait()
        self.assertEqual(len(self.db.locks), 1)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertEqual(self.db.locks, {})
        self.assertFalse(service.download_pool.pool.checked_out)

    async def test_uncertain_reset_poison_closes_exact_connection_and_denies_new_streams(
        self,
    ):
        service = self.service()
        self.db.reset_failure = True
        await self.run_response(service)
        self.assertTrue(service.download_pool.closing)
        self.assertTrue(self.db.connections[0].closed)
        self.assertEqual(self.db.locks, {})
        with self.assertRaises(WorkspaceError) as denied:
            await download.response(ModelRequest(), self.session(), service, JOB)
        self.assertEqual(denied.exception.status, 503)

    async def test_second_cancellation_cannot_orphan_release(self):
        gate, entered = asyncio.Event(), asyncio.Event()

        async def release():
            entered.set()
            await gate.wait()

        task = asyncio.create_task(download._finish(release()))
        await entered.wait()
        task.cancel()
        await asyncio.sleep(0)
        task.cancel()
        await asyncio.sleep(0)
        self.assertFalse(task.done())
        gate.set()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_real_sixty_second_deadline_before_body_performs_no_sql(self):
        service = self.service()
        request = ModelRequest()
        request.incoming.get_nowait()
        started = asyncio.get_running_loop().time()
        with self.assertRaises(download.Interrupted):
            await self.run_response(service, request=request)
        elapsed = asyncio.get_running_loop().time() - started
        self.assertGreaterEqual(elapsed, 59.9)
        self.assertLess(elapsed, 62)
        self.assertEqual(self.db.queries, [])
        self.assertEqual(service.download_pool.active, set())


if __name__ == "__main__":
    unittest.main(verbosity=2)
