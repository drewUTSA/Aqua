"""Actual API forwarding and explicit synthetic mailbox/clock controls."""

import base64
import re
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import urlsplit

from p05_browser_protocol import MAX_BODY, PATHS
from p06_browser_routes import workspace_route


def dispatch(
    item: dict[str, Any],
    client: Any,
    service: Any,
    deliver: Callable[[], bool],
    captured: list[dict[str, str]],
    analysis: Any = None,
) -> dict[str, Any]:
    identifier = item["id"]
    kind = item.get("kind")
    if kind in {"workspace_grant", "workspace_revoke", "workspace_stats"}:
        if analysis is None:
            raise ValueError("fixture_analysis_not_enabled")
        return analysis.control(item)
    if kind == "mailbox":
        purpose = item.get("purpose")
        subjects = {
            "verify_email": "AQUA: Verify your email",
            "reset_password": "AQUA: Reset your password",
            "password_changed": "AQUA password changed",
        }
        if purpose not in subjects:
            raise ValueError("fixture_mail_purpose_invalid")
        for _ in range(8):
            selected = next(
                (p for p in captured if p["subject"] == subjects[purpose]), None
            )
            if selected is not None:
                captured.remove(selected)
                proof = re.search(
                    r"#token=([A-Za-z0-9_-]{43})(?:\n|$)", selected["text"]
                )
                result: dict[str, Any] = {
                    "id": identifier,
                    "kind": "mailbox",
                    "found": True,
                    "payload": selected,
                }
                if proof:
                    result["proof"] = proof[1]
                return result
            deliver()
            time.sleep(1.05)
        return {"id": identifier, "kind": "mailbox", "found": False}
    if kind == "recover_rates":
        # Explicit fixture clock step, never a public route or mailbox-budget bypass.
        with service.transaction() as conn:
            for table in ("auth_admission", "password_admission"):
                conn.execute(
                    f"UPDATE app.{table} SET expires_at=clock_timestamp()-interval '1 second'"
                )
        return {
            "id": identifier,
            "kind": "recovered",
            "scope": "synthetic_admission_windows_only",
        }
    if kind != "request":
        raise ValueError("fixture_operation_invalid")
    path, method = item.get("path"), item.get("method")
    if (
        not isinstance(path, str)
        or len(path) > 2048
        or not path.startswith("/api/")
        or "\\" in path
        or any(ord(c) < 32 for c in path)
        or not (
            (
                urlsplit(path).path in PATHS
                and method in {"GET", "POST", "HEAD", "OPTIONS"}
            )
            or workspace_route(path, method)
        )
    ):
        raise ValueError("fixture_request_invalid")
    headers = item.get("headers", [])
    if (
        not isinstance(headers, list)
        or len(headers) > 40
        or any(
            not isinstance(h, list)
            or len(h) != 2
            or any(not isinstance(v, str) for v in h)
            or any("\r" in v or "\n" in v for v in h)
            for h in headers
        )
        or sum(len(n) + len(v) for n, v in headers) > 8192
    ):
        raise ValueError("fixture_headers_invalid")
    body = base64.b64decode(item.get("bodyBase64", ""), validate=True)
    if len(body) > MAX_BODY:
        raise ValueError("fixture_body_limit")
    # Browser cookies are the only cookie authority. TestClient must not merge
    # a previous browser/tab's jar into a later request with no Cookie header.
    client.cookies.clear()
    try:
        response = client.request(
            method,
            path,
            headers=[
                (n, v)
                for n, v in headers
                if n.lower() not in {"host", "content-length", "connection"}
            ],
            content=body,
            follow_redirects=False,
        )
        if len(response.content) > MAX_BODY:
            raise ValueError("fixture_response_body_limit")
        return {
            "id": identifier,
            "status": response.status_code,
            "headers": [
                [n, v]
                for n, v in response.headers.multi_items()
                if n.lower() not in {"connection", "transfer-encoding"}
            ],
            "bodyBase64": base64.b64encode(response.content).decode(),
        }
    finally:
        client.cookies.clear()
