"""Bound connection/queue work and erase session state before pool reuse."""

from contextlib import contextmanager
import logging
from collections.abc import Iterator
import threading

import psycopg
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout, TooManyRequests

from storage.config import StorageSettings

log = logging.getLogger("aqua.storage")
SCHEMA_VERSION = 2


class StorageUnavailable(RuntimeError):
    """Private driver errors never become response/log payloads."""


def _configure(conn: psycopg.Connection) -> None:
    database, user, privileged = conn.execute(
        "SELECT current_database(), current_user, rolsuper OR rolcreaterole OR rolcreatedb OR rolbypassrls "
        "FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    if (database, user, privileged) != ("aqua_app", "aqua_app_runtime", False):
        raise StorageUnavailable("application_storage_role_invalid")


def _reset(conn: psycopg.Connection) -> None:
    """DISCARD ALL requires autocommit; prepared statements are disabled below."""
    try:
        conn.execute("DISCARD ALL")
    except psycopg.Error:
        raise StorageUnavailable("application_storage_reset_failed") from None


class Storage:
    def __init__(self, settings: StorageSettings) -> None:
        self.settings = settings
        self._pool: ConnectionPool | None = None
        self._lock = threading.Lock()

    def open(self) -> None:
        if not self.settings.enabled:
            return
        with self._lock:
            if self._pool is None:
                self._pool = ConnectionPool(
                    self.settings.dsn,
                    min_size=0,
                    max_size=self.settings.max_connections,
                    max_waiting=self.settings.max_waiting,
                    timeout=self.settings.wait_seconds,
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
                    check=ConnectionPool.check_connection,
                    name="aqua-private-storage",
                )
                self._pool.open(wait=False)

    def close(self) -> None:
        with self._lock:
            if self._pool is not None:
                self._pool.close(timeout=5)

    @contextmanager
    def transaction(self) -> Iterator[psycopg.Connection]:
        if not self.settings.enabled:
            raise StorageUnavailable("application_storage_disabled")
        self.open()
        assert self._pool is not None
        try:
            with self._pool.connection(timeout=self.settings.wait_seconds) as conn:
                with conn.transaction():
                    # Every lease gets bounded SQL and only the intended namespaces.
                    conn.execute("SET LOCAL search_path = pg_catalog, app")
                    conn.execute("SET LOCAL statement_timeout = '3s'")
                    conn.execute("SET LOCAL lock_timeout = '1s'")
                    conn.execute(
                        "SET LOCAL idle_in_transaction_session_timeout = '10s'"
                    )
                    yield conn
        except (psycopg.Error, PoolClosed, PoolTimeout, TooManyRequests):
            log.warning("application_storage_failure action=deny")
            raise StorageUnavailable("application_storage_unavailable") from None

    def readiness(self) -> dict[str, str | int]:
        if not self.settings.enabled:
            return {"status": "ready", "application_storage": "disabled"}
        with self.transaction() as conn:
            row = conn.execute(
                "SELECT version FROM app.schema_migrations ORDER BY version DESC LIMIT 1"
            ).fetchone()
            if row != (SCHEMA_VERSION,):
                raise StorageUnavailable("application_storage_schema_unavailable")
        return {
            "status": "ready",
            "application_storage": "ready",
            "schema_version": SCHEMA_VERSION,
        }
