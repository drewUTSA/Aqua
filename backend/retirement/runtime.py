"""One checked independent protocol connection; application dumps cannot rewind it."""

import os
import sys
from contextlib import contextmanager

from psycopg_pool import ConnectionPool

from retirement.checkpoint import ProtectedFile
from retirement.client import AuthorityClient
from retirement.interlock import Broker, RetirementUnavailable
from retirement.settings import DIRECTORY, FLAG, load


def _pool(settings):
    if any(name.startswith("PG") for name in os.environ):
        raise RetirementUnavailable()

    def configure(conn):
        conn.execute("SET search_path=pg_catalog,retirement")
        conn.execute("SET statement_timeout='3s'")
        conn.execute("SET lock_timeout='1s'")
        conn.execute("SET idle_in_transaction_session_timeout='10s'")
        conn.execute("SET timezone='UTC'")
        row = conn.execute(
            "SELECT current_database(),current_user,session_user,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if row != (
            "aqua_retirement",
            "aqua_retirement_writer",
            "aqua_retirement_writer",
            False,
            False,
            False,
            False,
            False,
            False,
            1,
        ):
            raise RetirementUnavailable()
        if conn.execute(
            "SELECT has_database_privilege(current_user,current_database(),'TEMP'),has_schema_privilege(current_user,'retirement','CREATE'),pg_has_role(current_user,'aqua_retirement_owner','MEMBER'),has_table_privilege(current_user,'retirement.intents','INSERT,UPDATE,DELETE,TRUNCATE')"
        ).fetchone() != (False, False, False, False):
            raise RetirementUnavailable()
        for name in ("fsync", "full_page_writes", "synchronous_commit"):
            if conn.execute("SHOW " + name).fetchone() != ("on",):
                raise RetirementUnavailable()

    def reset(conn):
        conn.execute("DISCARD ALL")

    return ConnectionPool(
        settings.dsn,
        min_size=0,
        max_size=1,
        max_waiting=1,
        num_workers=1,
        timeout=1,
        reconnect_timeout=3,
        max_lifetime=300,
        max_idle=30,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 2},
        configure=configure,
        reset=reset,
        check=ConnectionPool.check_connection,
        name="aqua-retirement-authority",
    )


class Runtime:
    def __init__(self, storage, *, client=None, enabled=False):
        self.storage, self.client, self.enabled = storage, client, enabled
        self.pool = None
        self.ready = False

    @property
    def installed(self):
        return self.client is not None

    def start(self):
        if not self.storage.settings.enabled:
            if self.installed or self.enabled:
                raise RetirementUnavailable()
            self.ready = True
            return
        if self.client is None:
            with self.storage.transaction() as conn:
                if conn.execute(
                    "SELECT (SELECT count(*) FROM app.retirement_intents),authority_installed,EXISTS(SELECT 1 FROM pg_database WHERE datname='aqua_retirement') FROM app.retirement_control WHERE singleton"
                ).fetchone() != (0, False, False):
                    raise RetirementUnavailable()
            self.ready = True
            return
        if self.pool is not None:
            self.pool.open(wait=False)
        from retirement.mail_physical import validate as validate_mail_lock

        validate_mail_lock()
        head = self.client.startup_checkpoint()
        from retirement.startup import validate

        validate(self.storage, self.client, head)
        with self.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.retirement_control SET authority_installed=true WHERE singleton"
            )
        self.ready = True

    def capable(self):
        return self.enabled and self.ready and self.client is not None

    @contextmanager
    def purge_guard(self, closed):
        if not closed:
            yield True
            return
        from retirement.mail_physical import gate

        with gate() as acquired:
            yield acquired

    def close(self):
        self.ready = False
        if self.pool is not None:
            self.pool.close(timeout=3)


def create(storage):
    settings = load()
    runtime = Runtime(storage, enabled=os.environ.get(FLAG, "false") == "true")
    if settings is not None:
        from privacy.policy import runtime_context

        # Installed retirement remains mandatory even with new deletions off.
        # Its process-global commit interlock requires the reviewed topology.
        if (
            not runtime_context(sys.argv)
            or storage.settings.max_connections != 4
            or any(
                os.environ.get(name, "1") != "1"
                for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
            )
            or os.environ.get("UVICORN_RELOAD", "false") != "false"
            or any(
                os.environ.get(name, "")
                for name in ("GUNICORN_CMD_ARGS", "SERVER_SOFTWARE")
            )
        ):
            raise RetirementUnavailable()
        protected = ProtectedFile(
            DIRECTORY / "checkpoints.bin",
            owner_uid=1000,
            public_key=settings.public_key,
            installation=settings.installation,
            key_id=settings.identity.key_id,
            commitment=settings.identity.commitment,
        )
        runtime.pool = _pool(settings)
        runtime.client = AuthorityClient(
            Broker(
                runtime.pool,
                settings.installation,
                key=settings.identity,
                checkpoint=protected,
            )
        )
    storage.retirement = runtime
    return runtime
