"""Real Uvicorn/auth/storage/dispatcher; only fixed synthetic analysis is fake."""

from dataclasses import dataclass, replace
import logging
import os
import secrets
import socket
import threading
import time

from mixed_capacity_contract import JOB_QUESTIONS, LIMITS

DSN = (
    "postgresql://aqua_app_runtime:fixture-only@127.0.0.1:5432/aqua_app?sslmode=disable"
)
MIGRATOR = DSN.replace("runtime", "migrator")
DATASET = "p12-fixed-fake-analysis-no-analytical-connection"


def guard(port):
    """Deny Python network and libpq except the exact local HTTP/private DB."""
    import psycopg

    connect, resolve = socket.socket.connect, socket.getaddrinfo
    database = psycopg.Connection.connect.__func__

    def refuse(*args, **kwargs):
        raise AssertionError("mixed_external_transport_denied")

    def local_connect(sock, address):
        if (
            sock.family == socket.AF_UNIX
            or sock.family == socket.AF_INET
            and address == ("127.0.0.1", port)
        ):
            return connect(sock, address)
        return refuse()

    def local_resolve(host, requested_port, *args, **kwargs):
        if host != "127.0.0.1" or requested_port != port:
            return refuse()
        return resolve(host, requested_port, *args, **kwargs)

    def local_database(cls, conninfo="", **kwargs):
        if conninfo not in {DSN, MIGRATOR} or set(kwargs) - {
            "autocommit",
            "prepare_threshold",
            "connect_timeout",
        }:
            return refuse()
        return database(cls, conninfo, **kwargs)

    socket.socket.connect, socket.getaddrinfo = local_connect, local_resolve
    socket.socket.connect_ex = refuse
    psycopg.Connection.connect = classmethod(local_database)
    psycopg.connect = psycopg.Connection.connect
    psycopg.AsyncConnection.connect = classmethod(refuse)


class FixedEngine:
    """Six fixed fake jobs preserve real admission/control/settlement boundaries."""

    def __init__(self, owners):
        self.owners = frozenset(owners)
        self.lock, self.closed = threading.Lock(), threading.Event()
        self.active = self.maximum_active = self.started = self.completed = (
            self.cancelled
        ) = 0
        self.entered = {question: threading.Event() for question in JOB_QUESTIONS[:2]}

    def run(self, payload, control):
        from analysis.dispatch import Halt
        from nl2sql.pipeline import Answer
        from nl2sql.response import to_response

        question = payload["question"]
        if (
            payload["principal"] not in self.owners
            or payload["settings"]["database_url"] != DATASET
            or question not in JOB_QUESTIONS
        ):
            raise AssertionError("mixed_fake_payload_denied")
        with self.lock:
            if (
                self.closed.is_set()
                or self.started >= LIMITS["fake_jobs"]
                or self.active >= 2
            ):
                raise AssertionError("mixed_fake_work_bound")
            self.started += 1
            self.active += 1
            self.maximum_active = max(self.maximum_active, self.active)
        try:
            control("generating")
            if question == JOB_QUESTIONS[1]:
                control("executing")
            if question in self.entered:
                self.entered[question].set()
                until = time.monotonic() + 30
                while not self.closed.wait(0.05):
                    control(None)
                    if time.monotonic() >= until:
                        raise Halt("interrupted")
                raise Halt("interrupted")
            control("validating")
            control("executing")
            time.sleep(0.04)
            control("summarizing")
            result = to_response(
                Answer(
                    question,
                    "SELECT 7 AS fixture_value",
                    columns=["fixture_value"],
                    rows=[(7,)],
                    model="fixture-only",
                )
            )
            with self.lock:
                self.completed += 1
            return result, 200
        except Halt as error:
            if error.state == "cancelled":
                with self.lock:
                    self.cancelled += 1
            raise
        finally:
            with self.lock:
                self.active -= 1

    def close(self):
        self.closed.set()

    def report(self):
        with self.lock:
            return {
                "started": self.started,
                "completed": self.completed,
                "cancelled": self.cancelled,
                "physical_fake_active": self.active,
                "maximum_physical_fake_active": self.maximum_active,
                "actual_provider_calls": 0,
                "child_process_exit_tested": False,
            }


@dataclass(frozen=True)
class Actor:
    owner: str
    cookie: str
    csrf: str
    granted: bool


class Runtime:
    def __init__(self):
        self.listener = self.storage = self.engine = self.server = self.thread = (
            self.analysis
        ) = None
        self.provider_attempts = 0
        self.failure = None
        self.phase = "setup"

    def start(self):
        # This is the already network-none disposable runner's environment only.
        os.environ.clear()
        os.environ.update(
            PATH="/usr/local/bin:/usr/bin:/bin",
            PYTHON_DOTENV_DISABLED="1",
            PYTHONDONTWRITEBYTECODE="1",
            APP_STORAGE_ENABLED="false",
            DATABASE_URL="",
        )
        logging.disable(logging.CRITICAL)
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(16)
        self.port = self.listener.getsockname()[1]
        guard(self.port)
        import main
        import psycopg
        import uvicorn
        from auth.config import load_auth_policy
        from auth.sessions import (
            bound_value,
            new_token,
            session_cookie_name,
            token_digest,
        )
        from auth.store import IdentityStore
        from analysis.service import Analysis
        from analysis import policy as analysis_policy
        from google import genai
        from storage.config import StorageSettings
        from storage.migrate import apply
        from storage.pool import Storage

        assert (
            analysis_policy.RUNNING_GLOBAL,
            analysis_policy.RUNNING_OWNER,
            analysis_policy.DEADLINE_SECONDS,
        ) == (2, 1, 120)
        with psycopg.connect(MIGRATOR, autocommit=True) as conn:
            assert apply(conn) == 9
        self.storage = Storage(StorageSettings(True, DSN, 4, 8, 2))
        self.settings = replace(
            main.app.state.settings,
            database_url=DATASET,
            retrieval=False,
            app_origin=f"http://127.0.0.1:{self.port}",
            session_secret=secrets.token_urlsafe(64),
            google_client_id="",
            auth_allowed_emails=frozenset(),
            auth_allowed_google_subs=frozenset(),
        )
        policy = load_auth_policy(self.settings)
        store = IdentityStore(self.storage, policy)
        self.actors, self.history = [], {}
        for index in range(4):
            raw = new_token()
            csrf = bound_value(self.settings, raw, "session-csrf")
            identity = {
                "sub": f"p12-fixed-owner-{index}",
                "email": f"p12.reader{index}@example.test",
                "email_verified": True,
                "name": f"Synthetic reader {index}",
                "picture": "",
            }
            session = store.login(
                identity,
                token_digest(raw),
                token_digest(csrf),
                "fixture-peer",
                self.settings,
            )
            owner = session.user["id"]
            self.actors.append(
                Actor(
                    owner,
                    f"{session_cookie_name(self.settings)}={raw}",
                    csrf,
                    index < 2,
                )
            )
            with self.storage.transaction() as conn:
                if index < 2:
                    conn.execute(
                        "INSERT INTO app.dataset_grants(user_id,dataset_key) VALUES(%s,%s)",
                        (owner, policy.dataset_key),
                    )
                rows = conn.execute(
                    "INSERT INTO app.chats(user_id,title) SELECT %s,'Synthetic history '||n FROM generate_series(1,20)n RETURNING id",
                    (owner,),
                ).fetchall()
                self.history[owner] = {str(row[0]) for row in rows}
        self.engine = FixedEngine(actor.owner for actor in self.actors[:2])
        self.analysis = Analysis(
            self.storage,
            policy,
            self.settings.session_secret,
            self.settings,
            engine=self.engine,
        )
        main.app.state.settings, main.app.state.storage, main.app.state.analysis = (
            self.settings,
            self.storage,
            self.analysis,
        )

        def no_provider(*args, **kwargs):
            self.provider_attempts += 1
            raise AssertionError("mixed_real_provider_denied")

        genai.Client = main.answer_question = main.get_schema = no_provider
        self.server = uvicorn.Server(
            uvicorn.Config(
                main.app,
                host="127.0.0.1",
                port=self.port,
                log_config=None,
                access_log=False,
                log_level="critical",
                timeout_keep_alive=2,
                timeout_graceful_shutdown=5,
            )
        )

        def serve():
            try:
                self.server.run(sockets=[self.listener])
            except BaseException as error:
                self.failure = type(error).__name__

        self.thread = threading.Thread(
            target=serve, name="p12-loopback-http", daemon=True
        )
        self.thread.start()

    def close(self):
        if self.engine is not None:
            self.engine.close()
        if self.server is not None:
            self.server.should_exit = True
        if self.thread is not None:
            self.thread.join(timeout=LIMITS["app_shutdown_seconds"])
        if self.listener is not None:
            self.listener.close()
        if self.thread is None and self.storage is not None:
            self.storage.close()
        return {
            "server_exited": self.thread is None or not self.thread.is_alive(),
            "dispatcher_threads_exited": self.analysis is None
            or all(not thread.is_alive() for thread in self.analysis.threads),
            "fake_work_exited": self.engine is None or self.engine.active == 0,
        }
