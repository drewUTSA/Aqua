"""Real FastAPI/private-storage fixture with fake Google and mail only."""

import json
import logging
import os
import re
import secrets
import socket
import sys
from dataclasses import replace
from typing import Any

from p05_browser_docker import ROOT
from p05_browser_messages import dispatch
from p05_browser_protocol import (
    DSN,
    GOOGLE_EMAIL,
    GOOGLE_SUBJECT,
    MAIL_ORIGIN,
    MAX_BODY,
    MAX_REQUESTS,
    MAX_SECONDS,
    MIGRATOR,
    emit,
    message,
)

WORKER_STAGE = "before_start"


def guard_fixture() -> None:
    """Python TCP/DNS and libpq are denied except two exact socket fixture DSNs."""
    import psycopg

    connect = socket.socket.connect
    database = psycopg.Connection.connect.__func__

    def socket_connect(sock: socket.socket, address: Any) -> Any:
        if sock.family != socket.AF_UNIX:
            raise AssertionError("fixture_network_access_denied")
        return connect(sock, address)

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("fixture_network_access_denied")

    def database_connect(cls: Any, conninfo: str = "", **kwargs: Any) -> Any:
        if conninfo not in {DSN, MIGRATOR} or set(kwargs) - {
            "autocommit",
            "connect_timeout",
            "prepare_threshold",
        }:
            raise AssertionError("fixture_database_access_denied")
        return database(cls, conninfo, **kwargs)

    socket.socket.connect = socket_connect
    socket.socket.connect_ex = refuse
    socket.getaddrinfo = refuse
    psycopg.Connection.connect = classmethod(database_connect)
    psycopg.connect = psycopg.Connection.connect


def worker(origin: str) -> int:
    """Actual app/router/session/password code; only provider and mail are fakes."""
    global WORKER_STAGE
    WORKER_STAGE = "environment"
    sys.path.insert(0, str(ROOT / "backend"))
    for key in list(os.environ):
        if key.startswith(("PG", "APP_", "AUTH_", "PASSWORD_", "ACCOUNT_")) or key in {
            "DATABASE_URL",
            "INDEXER_DATABASE_URL",
            "GEMINI_API_KEY",
            "GOOGLE_API_KEY",
            "GOOGLE_CLIENT_ID",
            "SESSION_SECRET",
            "RESEND_API_KEY",
            "RETRIEVAL",
        }:
            del os.environ[key]
    os.environ.update(
        PYTHON_DOTENV_DISABLED="1",
        APP_STORAGE_ENABLED="false",
        DATABASE_URL="",
        PASSWORD_AUTH_ENABLED="true",
        PASSWORD_REGISTRATION_ENABLED="true",
        PASSWORD_RECOVERY_ENABLED="true",
    )
    logging.disable(logging.CRITICAL)
    guard_fixture()
    WORKER_STAGE = "app_import"
    import main
    import psycopg
    from auth import password_router, router
    from auth.config import load_auth_policy
    from auth.mailconfig import MailPolicy
    from auth.mailqueue import MailOutbox
    from auth.mailworker import MailWorker
    from auth.password_policy import PasswordPolicy
    from auth.passwords import PasswordStore
    from fastapi.testclient import TestClient
    from storage.config import StorageSettings
    from storage.migrate import apply
    from storage.pool import Storage

    WORKER_STAGE = "migration"
    with psycopg.connect(MIGRATOR, autocommit=True, connect_timeout=2) as conn:
        apply(conn)
    WORKER_STAGE = "runtime_configuration"
    service = Storage(StorageSettings(True, DSN, 2, 4, 2))
    settings = replace(
        main.app.state.settings,
        app_origin=origin,
        database_url="",
        session_secret=secrets.token_urlsafe(64),
        google_client_id="p05-fixture-client.apps.googleusercontent.com",
        auth_allowed_emails=frozenset(),
        auth_allowed_google_subs=frozenset(),
        retrieval=False,
    )
    main.app.state.settings, main.app.state.storage = settings, service
    policy = MailPolicy(
        enabled=True, key=secrets.token_bytes(32), public_origin=MAIL_ORIGIN
    )
    store = PasswordStore(service, load_auth_policy(settings), PasswordPolicy(), policy)
    main.app.dependency_overrides[password_router.get_password_store] = lambda: store
    captured: list[dict[str, str]] = []

    class Capture:
        def send(self, job_id: Any, payload: dict[str, str]) -> str:
            if len(captured) >= 16:
                raise AssertionError("fixture_mailbox_limit")
            captured.append(payload.copy())
            return "accepted"

    mail = MailWorker(MailOutbox(service, policy), Capture())

    def verify(credential: str, client_id: str) -> dict[str, Any]:
        value = json.loads(credential)
        if (
            not isinstance(value, dict)
            or set(value) != {"nonce"}
            or not isinstance(value["nonce"], str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", value["nonce"])
        ):
            raise ValueError("fixture_credential_invalid")
        return {
            "sub": GOOGLE_SUBJECT,
            "email": GOOGLE_EMAIL,
            "email_verified": True,
            "name": "Fixture Google Reader",
            "picture": "",
            "nonce": value["nonce"],
        }

    def no_pipeline(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("fixture_private_query_pipeline_was_invoked")

    router.verify_google_token = verify
    main.answer_question = no_pipeline
    main.get_schema = no_pipeline
    from google import genai

    genai.Client = no_pipeline
    WORKER_STAGE = "client_readiness"
    try:
        with TestClient(
            main.app, base_url=origin, raise_server_exceptions=True
        ) as client:
            readiness = service.readiness()
            if readiness.get("schema_version") != 3:
                raise RuntimeError("fixture_schema_invalid")
            emit(
                {
                    "kind": "ready",
                    "schema_version": 3,
                    "origin": origin,
                    "mail_origin": MAIL_ORIGIN,
                    "google_email": GOOGLE_EMAIL,
                    "google_subject": GOOGLE_SUBJECT,
                    "dataset_grants": 0,
                    "network": "none",
                    "database_transport": "private_unix_socket",
                    "max_requests": MAX_REQUESTS,
                    "max_seconds": MAX_SECONDS,
                    "body_bytes_max": MAX_BODY,
                    "capabilities": {
                        "password_login": True,
                        "google_login": True,
                        "durable_sessions": True,
                    },
                    "mail_origin_override": "fixture-only canonical HTTPS mailbox links; app Origin is exact supplied loopback",
                }
            )
            for _ in range(MAX_REQUESTS):
                item = message()
                if item is None:
                    return 0
                response = dispatch(item, client, service, mail.once, captured)
                emit(response)
    finally:
        main.app.dependency_overrides.clear()
        service.close()
    return 1
