"""Tripwires for accidental service access; Docker supplies the network boundary.

Install before importing application settings. Never accept a developer's normal
DATABASE_URL: integration tests select a fixed synthetic fixture by name.
"""

import os
import socket
from collections.abc import MutableMapping

import psycopg

DATASETS = {"bank", "pagila"}
CONFIG_NAMES = {
    "DATABASE_URL",
    "INDEXER_DATABASE_URL",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "GOOGLE_CLIENT_ID",
    "SESSION_SECRET",
    "APP_ORIGIN",
    "SESSION_MAX_AGE_SECONDS",
    "AUTH_ALLOWED_GOOGLE_SUBS",
    "AUTH_ALLOWED_EMAILS",
    "OLLAMA_BASE_URL",
    "OLLAMA_MODEL",
    "OLLAMA_THINK",
    "GEMINI_MODEL",
    "GEMINI_FALLBACK_MODELS",
    "GEMINI_EMBED_MODEL",
    "LLM_PROVIDER",
    "LLM_FALLBACK",
    "RETRIEVAL",
    "ANSWER_SIZE_RULES",
    "ANSWER_CACHE_SECONDS",
}


def configure(environ: MutableMapping[str, str]) -> str:
    """Discard inherited service configuration without reading or reporting it."""
    dataset = environ.get("AQUA_TEST_DATASET", "")
    if dataset and dataset not in DATASETS:
        raise RuntimeError("AQUA_TEST_DATASET must be bank or pagila")
    for name in list(environ):
        if name in CONFIG_NAMES or name.startswith("PG"):
            del environ[name]
    environ["PYTHON_DOTENV_DISABLED"] = "1"
    dsn = (
        f"postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_{dataset}"
        if dataset
        else ""
    )
    environ["DATABASE_URL"] = dsn
    return dsn


def install() -> None:
    """Block Python network use and libpq connections outside the fixture DSN."""
    dsn = configure(os.environ)
    original_connect = socket.socket.connect
    original_database_connect = psycopg.Connection.connect.__func__

    def socket_connect(sock, address):
        if sock.family == socket.AF_UNIX:
            return original_connect(sock, address)
        raise AssertionError("test network access denied")

    def refuse(*args, **kwargs):
        raise AssertionError("test network access denied")

    def database_connect(cls, conninfo="", **kwargs):
        # libpq bypasses Python sockets, so guard its public entry point as well.
        # No override options, service files, alternate hosts or inherited PG*.
        if not dsn or conninfo != dsn or set(kwargs) - {"connect_timeout"}:
            raise AssertionError("test database access denied")
        return original_database_connect(cls, conninfo, **kwargs)

    socket.socket.connect = socket_connect
    socket.socket.connect_ex = refuse
    socket.getaddrinfo = refuse
    psycopg.Connection.connect = classmethod(database_connect)
    psycopg.connect = psycopg.Connection.connect
