"""Real private APIs with fake identity/mail and explicitly opt-in fake analysis."""

import json
import logging
import os
import re
import secrets
import socket
import sys
from collections.abc import Callable
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
    MAX_SECONDS,
    MIGRATOR,
    emit,
    message,
    request_limit,
    fixture_schema,
)

WORKER_STAGE = "before_start"


def guard_fixture() -> None:
    """Python TCP/DNS and libpq are denied except two exact socket fixture DSNs."""
    import psycopg

    connect = socket.socket.connect
    database = psycopg.Connection.connect.__func__
    asynchronous_database = psycopg.AsyncConnection.connect.__func__

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

    async def asynchronous_database_connect(
        cls: Any, conninfo: str = "", **kwargs: Any
    ) -> Any:
        # Async libpq bypasses Python sockets too. Only the download runtime
        # connection is needed; no async migrator/backup or alternate host.
        if (
            conninfo != DSN
            or set(kwargs) - {"autocommit", "connect_timeout", "prepare_threshold"}
            or kwargs.get("autocommit", True) is not True
            or kwargs.get("connect_timeout", 2) != 2
            or kwargs.get("prepare_threshold") is not None
        ):
            raise AssertionError("fixture_database_access_denied")
        return await asynchronous_database(cls, conninfo, **kwargs)

    socket.socket.connect = socket_connect
    socket.socket.connect_ex = refuse
    socket.getaddrinfo = refuse
    psycopg.Connection.connect = classmethod(database_connect)
    psycopg.connect = psycopg.Connection.connect
    psycopg.AsyncConnection.connect = classmethod(asynchronous_database_connect)


def worker(
    origin: str,
    workspace_analysis: bool = False,
    *,
    analysis_factory: Callable[[Any, Any], Any] | None = None,
    account_security_fixture: bool = False,
    account_identity_fixture: bool = False,
    personal_export_fixture: bool = False,
) -> int:
    """Actual app/router/session/password code; only provider and mail are fakes."""
    global WORKER_STAGE
    if (
        type(account_security_fixture) is not bool
        or type(account_identity_fixture) is not bool
        or type(personal_export_fixture) is not bool
    ):
        raise ValueError("fixture_security_mode_invalid")
    if account_identity_fixture and (
        not account_security_fixture or fixture_schema(ROOT) not in {7, 8}
    ):
        raise ValueError("fixture_identity_mode_invalid")
    if personal_export_fixture and (
        not account_identity_fixture
        or not account_security_fixture
        or fixture_schema(ROOT) != 8
    ):
        raise ValueError("fixture_export_mode_invalid")
    if account_security_fixture:
        from p10b_browser_fixture import MAX_REQUESTS, secure_origin

        secure_origin(origin)
        if workspace_analysis is not True:
            raise ValueError("fixture_security_mode_invalid")
        operations = MAX_REQUESTS
    else:
        operations = request_limit(workspace_analysis)
    WORKER_STAGE = "environment"
    sys.path.insert(0, str(ROOT / "backend"))
    for key in list(os.environ):
        if key.startswith(("PG", "APP_", "AUTH_", "PASSWORD_", "ACCOUNT_")) or key in {
            "PRIVATE_DATA_EXPORT_ENABLED",
            "WEB_CONCURRENCY",
            "UVICORN_WORKERS",
            "UVICORN_RELOAD",
            "GUNICORN_CMD_ARGS",
            "SERVER_SOFTWARE",
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
    from storage.pool import SCHEMA_VERSION, Storage
    from p06_browser_analysis import DATASET
    from p07_browser_analysis import LifecycleFixture

    WORKER_STAGE = "migration"
    with psycopg.connect(MIGRATOR, autocommit=True, connect_timeout=2) as conn:
        apply(conn)
    WORKER_STAGE = "runtime_configuration"
    service = Storage(
        StorageSettings(True, DSN, 4 if personal_export_fixture else 2, 4, 2)
    )
    settings = replace(
        main.app.state.settings,
        app_origin=origin,
        database_url=DATASET if workspace_analysis else "",
        session_secret=secrets.token_urlsafe(64),
        google_client_id="p05-fixture-client.apps.googleusercontent.com",
        auth_allowed_emails=frozenset(),
        auth_allowed_google_subs=frozenset(),
        retrieval=False,
    )
    main.app.state.settings, main.app.state.storage = settings, service
    # An explicit test-module factory extends offline feature fixtures without
    # adding fake modes, credentials or alternate services to production code.
    analysis = (
        (analysis_factory or LifecycleFixture)(service, settings)
        if workspace_analysis
        else None
    )
    if analysis is not None:
        from analysis.service import Analysis

        runtime = Analysis(
            service,
            load_auth_policy(settings),
            settings.session_secret,
            settings,
            engine=analysis,
        )
        main.app.state.analysis = runtime

        def restart_analysis() -> None:
            previous = main.app.state.analysis
            previous.close()
            analysis.reopen()
            main.app.state.analysis = Analysis(
                service,
                load_auth_policy(settings),
                settings.session_secret,
                settings,
                engine=analysis,
                start=True,
            )

        analysis.restart = restart_analysis
    key = secrets.token_bytes(32)
    policy = MailPolicy(
        enabled=True,
        key=key,
        public_origin=origin if account_security_fixture else MAIL_ORIGIN,
    )
    if account_security_fixture:
        from p10b_browser_fixture import mail_environment

        os.environ.update(mail_environment(origin, key))
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
    previous_runtime_context = None
    if personal_export_fixture:
        from privacy import policy as privacy_policy

        # Explicit isolated test mode models only current-process argv. Actual
        # deployment/container topology is a separate release proof, never this.
        os.environ.update(
            {
                privacy_policy.ACTIVATION_FLAG: "true",
                "WEB_CONCURRENCY": "1",
                "UVICORN_WORKERS": "1",
                "UVICORN_RELOAD": "false",
            }
        )
        previous_runtime_context = privacy_policy.runtime_context
        privacy_policy.runtime_context = lambda argv, *, child=False: not child
    identity_fixture = None
    if account_identity_fixture:
        if personal_export_fixture:
            from p11a_browser_fixture import PrivacyFixture as IdentityFixture
        else:
            from p10c_browser_fixture import IdentityFixture

        identity_fixture = IdentityFixture(service, settings, analysis)
        identity_fixture.install()
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
            if readiness.get(
                "schema_version"
            ) != SCHEMA_VERSION or SCHEMA_VERSION != fixture_schema(ROOT):
                raise RuntimeError("fixture_schema_invalid")
            emit(
                {
                    "kind": "ready",
                    "schema_version": SCHEMA_VERSION,
                    "origin": origin,
                    "mail_origin": policy.public_origin,
                    "account_security_fixture": account_security_fixture,
                    "account_identity_fixture": account_identity_fixture,
                    "personal_export_fixture": personal_export_fixture,
                    "identity_fixture": (
                        identity_fixture.metadata() if identity_fixture else None
                    ),
                    "google_email": GOOGLE_EMAIL,
                    "google_subject": GOOGLE_SUBJECT,
                    "dataset_grants": 0,
                    "workspace_analysis_fixture": workspace_analysis,
                    "network": "none",
                    "database_transport": "private_unix_socket",
                    "max_requests": operations,
                    "max_seconds": MAX_SECONDS,
                    "body_bytes_max": MAX_BODY,
                    "capabilities": {
                        "password_login": True,
                        "google_login": True,
                        "durable_sessions": True,
                        "workspace_analysis": workspace_analysis,
                    },
                    "mail_origin_override": (
                        "reserved HTTPS origin fulfilled by CDP; no DNS/socket/TLS transport claim"
                        if account_security_fixture
                        else "fixture-only canonical HTTPS mailbox links; app Origin is exact supplied loopback"
                    ),
                }
            )
            for _ in range(operations):
                item = message()
                if item is None:
                    return 0
                WORKER_STAGE = "request_dispatch"
                if identity_fixture is not None:
                    forward = identity_fixture.dispatch
                elif account_security_fixture:
                    from p10b_browser_fixture import security_dispatch

                    forward = security_dispatch
                else:
                    forward = dispatch
                response = forward(item, client, service, mail.once, captured, analysis)
                emit(response)
    finally:
        if previous_runtime_context is not None:
            privacy_policy.runtime_context = previous_runtime_context
        if identity_fixture is not None:
            identity_fixture.clear()
        main.app.dependency_overrides.clear()
        service.close()
    return 1
