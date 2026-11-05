"""Finite export policy. No provider, filesystem, timer or activation side effect."""

import hashlib
import json
import re
from uuid import UUID

SCOPE = "personal_v1"
OPERATION = "data_export"
OUTPUT_SECONDS = 3600
PROOF_SECONDS = 300
MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_OWNER_BYTES = MAX_EXPORT_BYTES
MAX_GLOBAL_BYTES = 128 * 1024 * 1024
CHUNK_BYTES = 64 * 1024
MAX_CHUNKS = 512
MAX_OWNER_LIVE_JOBS = 1
MAX_QUEUED_WORKING = 4
MAX_OWNER_JOB_ROWS = 5
MAX_JOB_ROWS = 128
REVIEW_PAGE_SIZE = 5
MAX_CURSOR_CHARACTERS = 1024
SNAPSHOT_FETCH_ROWS = 16
MAX_RESULT_FRAGMENT_BYTES = 262144
MAX_SOURCE_ROW_BYTES = 524288
SNAPSHOT_SECONDS = 10
WORKER_LEASE_SECONDS = 15
JOB_DEADLINE_SECONDS = 120
MAX_CLAIMS = 3
DOWNLOAD_SECONDS = 60
ASGI_SEND_SECONDS = 2
GLOBAL_DOWNLOADS = 2
OWNER_DOWNLOADS = 1
DOWNLOAD_ACCOUNT_PER_MINUTE = 5
DOWNLOAD_GLOBAL_PER_MINUTE = 20
CLEANUP_CHUNKS = 64
RUNTIME_ROLE_CONNECTIONS = 12
MAX_PLANNED_RUNTIME_CONNECTIONS = 10
ACTIVATION_FLAG = "PRIVATE_DATA_EXPORT_ENABLED"
WEB_POOL_CONNECTIONS = 4
WORKER_POOL_CONNECTIONS = 1
DOWNLOAD_POOL_CONNECTIONS = 2
STATES = frozenset({"queued", "working", "ready", "expired", "failed"})
FAILURE_CODES = frozenset(
    {
        "source_too_large",
        "authority_changed",
        "interrupted",
        "unavailable",
        "encoding_failed",
    }
)
SHA256 = re.compile(r"[a-f0-9]{64}\Z")
CURSOR = re.compile(r"[A-Za-z0-9_.-]{1,1024}\Z")


def identifier(value: object) -> str:
    """Public UUIDs select an intent/job; none is a bearer credential."""
    if type(value) is not str:
        raise ValueError("export_identifier_invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("export_identifier_invalid") from None
    if str(parsed) != value:
        raise ValueError("export_identifier_invalid")
    return value


def target_digest(intent_id: object) -> bytes:
    """One exact intent + immutable scope, within P10's existing proof domain."""
    target = [SCOPE, identifier(intent_id)]
    payload = ["aqua-account-action-v1", OPERATION, target]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).digest()


def pool_budget(processes: object, web_pool: object, other_runtime: object = 1) -> int:
    """Only the reviewed single-web-process topology may activate exports."""
    if (
        type(processes) is not int
        or processes != 1
        or type(web_pool) is not int
        or web_pool != WEB_POOL_CONNECTIONS
        or type(other_runtime) is not int
        or other_runtime != 1
    ):
        raise ValueError("privacy_pool_inventory_invalid")
    total = (
        processes * (web_pool + WORKER_POOL_CONNECTIONS + DOWNLOAD_POOL_CONNECTIONS)
        + other_runtime
    )
    if total > MAX_PLANNED_RUNTIME_CONNECTIONS:
        raise ValueError("privacy_pool_budget_unavailable")
    return total


def runtime_context(argv, *, child=False):
    """Validate this process only; host-container absence needs release proof."""
    if child or not isinstance(argv, (list, tuple)) or not argv:
        return False
    executable = argv[0].replace("\\", "/").rsplit("/", 1)[-1]
    return executable == "uvicorn" and list(argv[1:]) == [
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
    ]


def activation(environ, argv, *, child=False):
    """Default off; the bool is an operator gate, never a topology discovery."""
    if environ.get(ACTIVATION_FLAG, "false") != "true":
        return False
    if any(
        environ.get(name, "1") != "1" for name in ("WEB_CONCURRENCY", "UVICORN_WORKERS")
    ):
        return False
    if environ.get("UVICORN_RELOAD", "false") != "false":
        return False
    if any(environ.get(name, "") for name in ("GUNICORN_CMD_ARGS", "SERVER_SOFTWARE")):
        return False
    return runtime_context(argv, child=child)
