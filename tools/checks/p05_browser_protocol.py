"""Bounds, fixed fixture identities and JSONL framing; no service access."""

import ast
import json
from pathlib import Path
import sys
from typing import Any
from urllib.parse import urlsplit

POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)
DEFAULT_IMAGE = "aqua-runtime:check"
MAIL_ORIGIN = "https://aqua-browser.example.test"
GOOGLE_EMAIL = "google.reader@example.test"
GOOGLE_SUBJECT = "p05-fixture-google-subject"
DSN = "host=/run/aqua-app-db port=5432 dbname=aqua_app user=aqua_app_runtime password=fixture-only sslmode=disable"
MIGRATOR = DSN.replace("aqua_app_runtime", "aqua_app_migrator")
MAX_LINE = 65536
MAX_BODY = 16384
MAX_REQUESTS = 256
MAX_SECONDS = 300


def fixture_schema(root: Path) -> int:
    """Read one bounded literal from the frozen source, without backend import."""
    path = root / "backend/storage/pool.py"
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 131072:
        raise ValueError("fixture_schema_source_invalid")
    tree = ast.parse(path.read_text())
    writes = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Name)
        and node.id == "SCHEMA_VERSION"
        and isinstance(node.ctx, ast.Store)
    ]
    values = [
        node.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == "SCHEMA_VERSION"
    ]
    if (
        len(writes) != 1
        or len(values) != 1
        or not isinstance(values[0], ast.Constant)
        or type(values[0].value) is not int
        or values[0].value not in {6, 7}
    ):
        raise ValueError("fixture_schema_source_invalid")
    return values[0].value


def request_limit(workspace_analysis: bool = False) -> int:
    """Only the explicit lifecycle exercise gets its reviewed larger allowance."""
    return 400 if workspace_analysis is True else MAX_REQUESTS


PATHS = {
    "/api/health",
    "/api/models",
    "/api/query",
    "/api/auth/config",
    "/api/auth/me",
    "/api/auth/google",
    "/api/auth/logout",
    "/api/auth/methods",
    "/api/v1/auth/bootstrap",
    "/api/v1/auth/registrations",
    "/api/v1/auth/email-verifications",
    "/api/v1/auth/password-login",
    "/api/v1/auth/password-reset-requests",
    "/api/v1/auth/password-resets",
}


def origin_value(value: str) -> str:
    """The browser server may choose only an explicit local high-port origin."""
    parsed = urlsplit(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname != "127.0.0.1"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.port is None
        or not 1024 <= parsed.port <= 65535
        or value != f"http://127.0.0.1:{parsed.port}"
    ):
        raise ValueError("fixture_origin_invalid")
    return value


def emit(value: dict[str, Any]) -> None:
    encoded = json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    if len(encoded) > MAX_LINE:
        raise ValueError("fixture_response_limit")
    sys.stdout.write(encoded + "\n")
    sys.stdout.flush()


def message() -> dict[str, Any] | None:
    raw = sys.stdin.buffer.readline(MAX_LINE + 1)
    if not raw:
        return None
    if len(raw) > MAX_LINE or not raw.endswith(b"\n"):
        raise ValueError("fixture_input_limit")
    item = json.loads(raw)
    if not isinstance(item, dict) or not isinstance(item.get("id"), (str, int)):
        raise TypeError("fixture_message_invalid")
    return item
