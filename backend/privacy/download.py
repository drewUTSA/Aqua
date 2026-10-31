"""Bound private delivery to physical DB sessions and the actual ASGI lifetime.

This module has no export file path, public token, synchronous stream iterator or
per-download thread. A cancelled send finishes before its advisory locks return.
"""

import asyncio
from contextlib import asynccontextmanager
from datetime import timedelta
import hashlib
import hmac
import logging
import threading

import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg_pool import AsyncConnectionPool, PoolClosed, PoolTimeout, TooManyRequests
from starlette.responses import StreamingResponse

from privacy import policy
from privacy.database import DOWNLOAD_LOCK, OWNER_DOWNLOAD_LOCK
from storage.pool import StorageUnavailable
from workspace.errors import WorkspaceError, failure

log = logging.getLogger("aqua.privacy")
POOL_ERRORS = (psycopg.Error, PoolClosed, PoolTimeout, TooManyRequests)
IMMUTABLE = (
    "id",
    "user_id",
    "session_id",
    "scope",
    "auth_epoch",
    "privacy_epoch",
    "created_at",
    "expires_at",
    "generation",
    "chunk_count",
    "output_bytes",
    "sha256",
    "contains_results",
    "dataset_key",
    "grant_version",
)


class Interrupted(RuntimeError):
    """A started attachment must end as a truncated stream, never a success."""


class PhysicalGate:
    """Process-wide ownership survives DB-session death during a blocked send.

    Activation separately requires one verified backend process/container. This
    registry has no clock or lease reclamation and is shared by every local pool.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.holders = {}
        self.poisoned = False

    def acquire(self, owner):
        with self.lock:
            if self.poisoned:
                raise StorageUnavailable("privacy_download_physical_unavailable")
            if (
                len(self.holders) >= policy.GLOBAL_DOWNLOADS
                or owner in self.holders.values()
            ):
                raise WorkspaceError("capacity_reached", 429)
            token = object()
            self.holders[token] = owner
            return token

    def release(self, token, owner):
        with self.lock:
            if self.holders.pop(token, None) != owner:
                self.poisoned = True
                raise StorageUnavailable(
                    "privacy_download_physical_release_unconfirmed"
                )


PHYSICAL = PhysicalGate()


async def _one(conn, query, values=(), *, mapping=False):
    async with conn.cursor(row_factory=dict_row if mapping else tuple_row) as cursor:
        await cursor.execute(query, values)
        return await cursor.fetchone()


async def _execute(conn, query, values=()):
    async with conn.cursor() as cursor:
        await cursor.execute(query, values)


async def _configure(conn):
    row = await _one(
        conn,
        "SELECT current_database(),current_user,rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls FROM pg_catalog.pg_roles WHERE rolname=current_user",
    )
    if row != ("aqua_app", "aqua_app_runtime", False):
        raise StorageUnavailable("privacy_storage_role_invalid")
    await _execute(conn, "SET search_path=pg_catalog,app")
    await _execute(conn, "SET statement_timeout='3s'")
    await _execute(conn, "SET lock_timeout='1s'")
    await _execute(conn, "SET idle_in_transaction_session_timeout='10s'")


async def _reset(conn):
    await _execute(conn, "DISCARD ALL")


@asynccontextmanager
async def _transaction(conn):
    async with conn.transaction():
        await _execute(conn, "SET LOCAL search_path=pg_catalog,app")
        await _execute(conn, "SET LOCAL statement_timeout='3s'")
        await _execute(conn, "SET LOCAL lock_timeout='1s'")
        await _execute(conn, "SET LOCAL idle_in_transaction_session_timeout='10s'")
        yield


async def _finish(operation):
    """Second cancellation cannot orphan cleanup or advertise a held slot free."""
    task = asyncio.ensure_future(operation)
    cancelled = False
    while not task.done():
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled = True
    result = task.result()
    if cancelled:
        raise asyncio.CancelledError
    return result


class DownloadPool:
    """Bound connections plus physical sends in the verified single process."""

    def __init__(self, settings):
        self.pool = AsyncConnectionPool(
            settings.dsn,
            min_size=0,
            max_size=policy.DOWNLOAD_POOL_CONNECTIONS,
            max_waiting=1,
            timeout=1,
            open=False,
            num_workers=1,
            reconnect_timeout=5,
            max_lifetime=300,
            max_idle=30,
            kwargs={
                "autocommit": True,
                "prepare_threshold": None,
                "connect_timeout": 2,
            },
            configure=_configure,
            reset=_reset,
            check=AsyncConnectionPool.check_connection,
            name="aqua-private-download",
        )
        self.opened = False
        self.closing = False
        self.active = set()
        self.open_lock = asyncio.Lock()

    async def _open(self):
        async with self.open_lock:
            if self.closing:
                raise StorageUnavailable("privacy_download_unavailable")
            if not self.opened:
                await self.pool.open(wait=False)
                self.opened = True

    @asynccontextmanager
    async def lifecycle(self, owner):
        if self.closing:
            raise StorageUnavailable("privacy_download_unavailable")
        token = PHYSICAL.acquire(owner)
        task = asyncio.current_task()
        self.active.add(task)
        try:
            yield
        finally:
            self.active.discard(task)
            PHYSICAL.release(token, owner)

    async def _release(self, conn):
        try:
            # DISCARD ALL releases session locks and erases state, synchronously
            # acknowledged by this exact DB session before it is reusable.
            await _reset(conn)
            row = await _one(
                conn,
                "SELECT NOT EXISTS(SELECT 1 FROM pg_catalog.pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory' AND granted)",
            )
            if row != (True,):
                raise StorageUnavailable("privacy_download_unlock_unconfirmed")
        except Exception:
            # Do not open replacement sessions after uncertain release. Closing
            # an async pool leaves other checked-out sends alone until return.
            self.closing = True
            await conn.close()
            await self.pool.close(timeout=3)
            log.warning("privacy_event action=download_cleanup reason=unavailable")
        finally:
            await self.pool.putconn(conn)

    @asynccontextmanager
    async def connection(self):
        await self._open()
        conn = await self.pool.getconn(timeout=1)
        try:
            if self.closing:
                raise StorageUnavailable("privacy_download_unavailable")
            # DISCARD resets session limits, so each lease rechecks role/limits.
            await _configure(conn)
            yield conn
        finally:
            await _finish(self._release(conn))

    async def aclose(self):
        self.closing = True
        current = asyncio.current_task()
        pending = tuple(task for task in self.active if task is not current)
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        # Never close the pool underneath a live ASGI task, including this task.
        if self.active:
            raise StorageUnavailable("privacy_download_drain_unconfirmed")
        await self.pool.close(timeout=3)


def _transport(request, session, settings):
    headers = {}
    for raw_name, raw_value in request.scope.get("headers", ()):
        name = raw_name.decode("latin-1").lower()
        headers.setdefault(name, []).append(raw_value.decode("latin-1"))
    single = (
        "x-csrf-token",
        "origin",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
        "content-length",
    )
    if any(len(headers.get(name, ())) > 1 for name in single):
        raise WorkspaceError("invalid_request", 422)

    def value(name, default=""):
        return headers.get(name, [default])[0]

    csrf = value("x-csrf-token")
    if (
        not csrf
        or len(csrf) > 128
        or not hmac.compare_digest(csrf.encode(), session.csrf_token.encode())
    ):
        raise WorkspaceError("session_invalid", 403)
    if value("origin", None) not in (None, settings.app_origin):
        raise WorkspaceError("session_invalid", 403)
    if value("sec-fetch-site", None) not in (None, "same-origin", "none"):
        raise WorkspaceError("session_invalid", 403)
    if (
        request.scope.get("method") != "GET"
        or request.scope.get("query_string", b"")
        or value("content-length", "0") != "0"
        or "transfer-encoding" in headers
        or any(
            name in headers for name in ("range", "if-range", "purpose", "sec-purpose")
        )
        or value("sec-fetch-mode", None) not in (None, "cors", "same-origin")
        or value("sec-fetch-dest") not in ("", "empty")
    ):
        raise WorkspaceError("invalid_request", 422)


async def _guard(conn, session):
    user = await _one(
        conn,
        "SELECT status,auth_epoch,privacy_epoch FROM app.users WHERE id=%s FOR UPDATE",
        (session.user["id"],),
    )
    if user is None or user[:2] != ("active", session.auth_epoch):
        raise WorkspaceError("not_found")
    row = await _one(
        conn,
        "SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s AND auth_epoch=%s AND revoked_at IS NULL AND idle_expires_at>clock_timestamp() AND absolute_expires_at>clock_timestamp() FOR SHARE",
        (session.user["id"], session.token_digest, session.auth_epoch),
    )
    if row is None:
        raise WorkspaceError("not_found")
    return str(row[0]), user[2]


async def _admit(conn, session):
    async with _transaction(conn):
        if await _one(conn, "SELECT max(version) FROM app.schema_migrations") != (8,):
            raise StorageUnavailable("privacy_storage_schema_unavailable")
        if await _one(
            conn, "SELECT singleton FROM app.privacy_control WHERE singleton FOR UPDATE"
        ) != (True,):
            raise StorageUnavailable("privacy_storage_control_unavailable")
        await _guard(conn, session)
        instant = (await _one(conn, "SELECT clock_timestamp()"))[0]
        await _execute(
            conn,
            "DELETE FROM app.privacy_admission WHERE (scope,key_digest) IN (SELECT scope,key_digest FROM app.privacy_admission WHERE expires_at<=%s ORDER BY expires_at,scope,key_digest LIMIT 64)",
            (instant,),
        )
        count = (await _one(conn, "SELECT count(*) FROM app.privacy_admission"))[0]
        updates = []
        for scope, value, maximum in (
            ("download:global", "all", policy.DOWNLOAD_GLOBAL_PER_MINUTE),
            (
                "download:account",
                session.user["id"],
                policy.DOWNLOAD_ACCOUNT_PER_MINUTE,
            ),
        ):
            key = hashlib.sha256(value.encode()).digest()
            row = await _one(
                conn,
                "SELECT hits,expires_at FROM app.privacy_admission WHERE scope=%s AND key_digest=%s",
                (scope, key),
            )
            count += row is None
            if count > 2048 or row and row[1] > instant and row[0] >= maximum:
                raise WorkspaceError("rate_limited", 429)
            updates.append((scope, key))
        for scope, key in updates:
            await _execute(
                conn,
                "INSERT INTO app.privacy_admission(scope,key_digest,hits,expires_at) VALUES(%s,%s,1,%s+interval '1 minute') ON CONFLICT(scope,key_digest) DO UPDATE SET hits=CASE WHEN app.privacy_admission.expires_at<=%s THEN 1 ELSE app.privacy_admission.hits+1 END,expires_at=CASE WHEN app.privacy_admission.expires_at<=%s THEN EXCLUDED.expires_at ELSE app.privacy_admission.expires_at END",
                (scope, key, instant, instant, instant),
            )


async def _slots(conn, owner):
    for slot in range(policy.GLOBAL_DOWNLOADS):
        if await _one(
            conn, "SELECT pg_try_advisory_lock(%s,%s)", (DOWNLOAD_LOCK, slot)
        ) == (True,):
            key = int.from_bytes(
                hashlib.sha256(owner.encode()).digest()[:4], "big", signed=True
            )
            if await _one(
                conn, "SELECT pg_try_advisory_lock(%s,%s)", (OWNER_DOWNLOAD_LOCK, key)
            ) == (True,):
                return
            if await _one(
                conn, "SELECT pg_advisory_unlock(%s,%s)", (DOWNLOAD_LOCK, slot)
            ) != (True,):
                raise StorageUnavailable("privacy_download_unlock_unconfirmed")
            break
    raise WorkspaceError("capacity_reached", 429)


async def _grant(conn, owner, auth_policy):
    if not auth_policy.dataset_key:
        return False, 0
    row = await _one(
        conn,
        "SELECT g.version,g.revoked_at,g.approval_kind,g.approval_evidence,e.subject,e.observed_email_key,e.email_authoritative,e.is_active FROM app.dataset_grants g LEFT JOIN app.external_identities e ON e.id=g.approval_identity_id AND e.user_id=g.user_id WHERE g.user_id=%s AND g.dataset_key=%s FOR SHARE OF g",
        (owner, auth_policy.dataset_key),
    )
    if row is None:
        return False, 0
    version, revoked, kind, evidence, subject, email, authoritative, active = row
    allowed = kind == "operator"
    if kind == "google_subject":
        allowed = (
            active
            and evidence == subject
            and evidence in auth_policy.allowed_google_subs
        )
    elif kind == "google_email":
        allowed = (
            active
            and authoritative
            and evidence == email
            and evidence in auth_policy.allowed_emails
        )
    return bool(allowed and revoked is None), version


def _validate(job, session, sid, epoch, now):
    if (
        job is None
        or str(job["user_id"]) != session.user["id"]
        or str(job["session_id"]) != sid
        or job["auth_epoch"] != session.auth_epoch
        or job["privacy_epoch"] != epoch
        or job["scope"] != policy.SCOPE
        or job["state"] != "ready"
        or job["expires_at"] <= now
    ):
        raise WorkspaceError("not_found")
    size, count = job["output_bytes"], job["chunk_count"]
    if (
        type(size) is not int
        or not 1 <= size <= policy.MAX_EXPORT_BYTES
        or type(count) is not int
        or count != (size + policy.CHUNK_BYTES - 1) // policy.CHUNK_BYTES
        or not 1 <= count <= policy.MAX_CHUNKS
        or type(job["generation"]) is not int
        or job["generation"] < 1
        or type(job["contains_results"]) is not bool
        or type(job["sha256"]) is not str
        or not policy.SHA256.fullmatch(job["sha256"])
        or job["expires_at"]
        != job["created_at"] + timedelta(seconds=policy.OUTPUT_SECONDS)
    ):
        raise StorageUnavailable("privacy_download_metadata_invalid")


async def _chunk(conn, session, service, job_id, ordinal, expected=None):
    if service.stopped.is_set() or service.download_pool.closing:
        raise StorageUnavailable("privacy_download_unavailable")
    async with _transaction(conn):
        sid, epoch = await _guard(conn, session)
        job = await _one(
            conn,
            "SELECT * FROM app.data_exports WHERE user_id=%s AND id=%s FOR SHARE",
            (session.user["id"], job_id),
            mapping=True,
        )
        now = (await _one(conn, "SELECT clock_timestamp()"))[0]
        _validate(job, session, sid, epoch, now)
        fingerprint = tuple(job[name] for name in IMMUTABLE)
        if expected is not None and fingerprint != expected:
            raise WorkspaceError("not_found")
        allowed, version = await _grant(conn, session.user["id"], service.policy)
        if job["contains_results"] and (
            not allowed
            or job["dataset_key"] != service.policy.dataset_key
            or job["grant_version"] != version
        ):
            raise WorkspaceError("not_found")
        row = await _one(
            conn,
            "SELECT body,digest FROM app.data_export_chunks WHERE user_id=%s AND job_id=%s AND generation=%s AND ordinal=%s",
            (session.user["id"], job_id, job["generation"], ordinal),
        )
        length = min(
            policy.CHUNK_BYTES, job["output_bytes"] - ordinal * policy.CHUNK_BYTES
        )
        if (
            row is None
            or not isinstance(row[0], (bytes, memoryview))
            or len(row[0]) != length
            or not isinstance(row[1], (bytes, memoryview))
            or len(row[1]) != 32
        ):
            raise StorageUnavailable("privacy_download_chunk_invalid")
        body = bytes(row[0])
        if not hmac.compare_digest(hashlib.sha256(body).digest(), bytes(row[1])):
            raise StorageUnavailable("privacy_download_chunk_invalid")
        return job, fingerprint, body


class DownloadResponse(StreamingResponse):
    def __init__(self, request, session, service, job_id):
        super().__init__(iter(()))
        self.request, self.session, self.service, self.job_id = (
            request,
            session,
            service,
            job_id,
        )
        self.started = self.called = False

    async def _send(self, send, message):
        async with asyncio.timeout(policy.ASGI_SEND_SECONDS):
            await send(message)

    async def _stream(self, send):
        try:
            async with self.service.download_pool.connection() as conn:
                await _admit(conn, self.session)  # Committed before any job lookup.
                await _slots(conn, self.session.user["id"])
                job, fingerprint, body = await _chunk(
                    conn, self.session, self.service, self.job_id, 0
                )
                headers = [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (
                        b"content-disposition",
                        b'attachment; filename="aqua-personal-data-v1.json"',
                    ),
                    (b"cache-control", b"private, no-store"),
                    (b"x-content-type-options", b"nosniff"),
                    (b"x-accel-buffering", b"no"),
                    (b"content-length", str(job["output_bytes"]).encode("ascii")),
                ]
                # Header send itself may await backpressure. Recheck again after
                # it, immediately before first bytes, just like every later chunk.
                self.started = True
                await self._send(
                    send,
                    {"type": "http.response.start", "status": 200, "headers": headers},
                )
                digest = hashlib.sha256()
                for ordinal in range(job["chunk_count"]):
                    _, _, body = await _chunk(
                        conn,
                        self.session,
                        self.service,
                        self.job_id,
                        ordinal,
                        fingerprint,
                    )
                    digest.update(body)
                    if ordinal == job["chunk_count"] - 1 and not hmac.compare_digest(
                        digest.hexdigest(), job["sha256"]
                    ):
                        raise StorageUnavailable("privacy_download_digest_invalid")
                    await self._send(
                        send,
                        {"type": "http.response.body", "body": body, "more_body": True},
                    )
                await self._send(
                    send,
                    {"type": "http.response.body", "body": b"", "more_body": False},
                )
        except Exception as error:
            if self.started:
                log.warning("privacy_event action=download reason=interrupted")
                raise Interrupted("private_export_interrupted") from None
            safe = (
                error
                if isinstance(error, WorkspaceError)
                else WorkspaceError("service_unavailable", 503)
            )
            await failure(safe)(
                self.request.scope,
                self.request.receive,
                lambda message: self._send(send, message),
            )

    async def __call__(self, scope, receive, send):
        if self.called:
            raise Interrupted("private_export_repeated_response")
        self.called = True
        try:
            async with self.service.download_pool.lifecycle(self.session.user["id"]):
                await self._run(scope, receive, send)
        except (WorkspaceError, StorageUnavailable) as error:
            if self.started:
                raise Interrupted("private_export_interrupted") from None
            safe = (
                error
                if isinstance(error, WorkspaceError)
                else WorkspaceError("service_unavailable", 503)
            )
            await failure(safe)(
                scope, receive, lambda message: self._send(send, message)
            )

    async def _run(self, scope, receive, send):
        work = disconnect = None
        try:
            async with asyncio.timeout(policy.DOWNLOAD_SECONDS):
                incoming = await receive()
                if incoming["type"] == "http.disconnect":
                    return
                if (
                    incoming["type"] != "http.request"
                    or incoming.get("body", b"")
                    or incoming.get("more_body", False)
                ):
                    await failure(WorkspaceError("invalid_request", 422))(
                        scope, receive, lambda message: self._send(send, message)
                    )
                    return
                work = asyncio.create_task(self._stream(send))
                disconnect = asyncio.create_task(receive())
                done, _ = await asyncio.wait(
                    (work, disconnect), return_when=asyncio.FIRST_COMPLETED
                )
                if disconnect in done:
                    work.cancel()
                else:
                    await work
        except TimeoutError:
            raise Interrupted("private_export_deadline") from None
        finally:
            for task in (work, disconnect):
                if task is not None and not task.done():
                    task.cancel()
            if work is not None or disconnect is not None:
                await _finish(
                    asyncio.gather(
                        *(task for task in (work, disconnect) if task is not None),
                        return_exceptions=True,
                    )
                )


async def response(request, session, service, job_id):
    """The router already paired cookie/CSRF before its first authentication SQL."""
    _transport(request, session, service.settings)
    try:
        policy.identifier(job_id)
        policy.identifier(session.user["id"])
    except (ValueError, KeyError):
        raise WorkspaceError("not_found") from None
    if (
        not service.configured
        or service.stopped.is_set()
        or service.download_pool is None
        or service.download_pool.closing
    ):
        raise WorkspaceError("service_unavailable", 503)
    return DownloadResponse(request, session, service, job_id)
