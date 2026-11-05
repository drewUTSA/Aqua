"""Dedicated bounded runtime connections retain physical session locks."""

from contextlib import contextmanager
import logging

import psycopg
from psycopg_pool import ConnectionPool, PoolClosed, PoolTimeout, TooManyRequests

from storage.pool import StorageUnavailable, _configure, _reset

log = logging.getLogger("aqua.privacy")
WORKER_LOCK = 1095848270
DOWNLOAD_LOCK = 1095848271
OWNER_DOWNLOAD_LOCK = 1095848272


@contextmanager
def transaction(conn, *, snapshot=False):
    try:
        with conn.transaction():
            if snapshot:
                conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            conn.execute("SET LOCAL search_path=pg_catalog,app")
            conn.execute("SET LOCAL statement_timeout='3s'")
            conn.execute("SET LOCAL lock_timeout='1s'")
            conn.execute("SET LOCAL idle_in_transaction_session_timeout='10s'")
            yield conn
    except psycopg.Error:
        log.warning("privacy_event action=database reason=unavailable")
        raise StorageUnavailable("privacy_storage_unavailable") from None


class PhysicalPool:
    def __init__(self, settings, maximum):
        self.settings = settings
        self.pool = ConnectionPool(
            settings.dsn,
            min_size=0,
            max_size=maximum,
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
            check=ConnectionPool.check_connection,
            name="aqua-private-export",
        )
        self.opened = False

    def open(self):
        if not self.opened:
            self.pool.open(wait=False)
            self.opened = True

    @contextmanager
    def connection(self):
        self.open()
        try:
            with self.pool.connection(timeout=1) as conn:
                yield conn
        except (psycopg.Error, PoolClosed, PoolTimeout, TooManyRequests):
            log.warning("privacy_event action=connection reason=unavailable")
            raise StorageUnavailable("privacy_storage_unavailable") from None

    def close(self):
        self.pool.close(timeout=3)


def global_lock(conn):
    # All privacy transactions acquire this row before user then job locks.
    return conn.execute(
        "SELECT reserved_bytes,stored_bytes,worker_owner,worker_until,worker_job FROM app.privacy_control WHERE singleton FOR UPDATE"
    ).fetchone()
