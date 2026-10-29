"""Closed reserved-HTTPS account fixture: no rate bypass or notice body exposure."""

import base64
import re
from typing import Any
from urllib.parse import urlsplit

from p05_browser_messages import dispatch

ORIGIN = "https://aqua-browser.example.test"
MAX_REQUESTS = 300


def secure_origin(value: str) -> str:
    """Chrome CDP fulfills this exact reserved origin; no TLS/socket is claimed."""
    if type(value) is not str or value != ORIGIN:
        raise ValueError("fixture_secure_origin_invalid")
    return value


def mail_environment(origin: str, key: bytes) -> dict[str, str]:
    secure_origin(origin)
    if type(key) is not bytes or len(key) != 32:
        raise ValueError("fixture_mail_key_invalid")
    return {
        "ACCOUNT_MAIL_ENABLED": "true",
        "ACCOUNT_PUBLIC_ORIGIN": origin,
        "ACCOUNT_MAIL_OUTBOX_KEY": base64.urlsafe_b64encode(key).decode("ascii"),
    }


def security_dispatch(
    item: dict, client: Any, service: Any, deliver: Any, captured: list, analysis: Any
) -> dict:
    """Only normal API calls/fake enrollment mail; never change time or grants."""
    kind = item.get("kind")
    if kind in {
        "recover_rates",
        "workspace_grant",
        "workspace_revoke",
        "workspace_release",
        "workspace_restart",
        "workspace_recover_analysis_rate",
    }:
        raise ValueError("fixture_security_control_denied")
    if kind == "mailbox" and item.get("purpose") == "password_changed":
        raise ValueError("fixture_security_notice_body_denied")
    if kind == "security_mail_status":
        if set(item) != {"id", "kind"}:
            raise ValueError("fixture_security_status_invalid")
        with service.transaction() as conn:
            rows = conn.execute(
                "SELECT state,count(*) FROM app.account_mail WHERE purpose='password_changed' GROUP BY state"
            ).fetchall()
        allowed = {"pending", "sending", "sent", "failed", "expired"}
        if any(
            state not in allowed or type(count) is not int or not 0 <= count <= 4096
            for state, count in rows
        ):
            raise ValueError("fixture_security_status_invalid")
        counts = dict(rows)
        return {
            "id": item["id"],
            "kind": kind,
            "purpose": "password_changed",
            "queued": counts.get("pending", 0) + counts.get("sending", 0),
            "completed": counts.get("sent", 0),
            "failed": counts.get("failed", 0) + counts.get("expired", 0),
            "body_exposed": False,
            "real_provider_calls": 0,
        }
    if kind == "request" and item.get("method") == "POST":
        path = urlsplit(item.get("path", "")).path
        if path == "/api/query" or re.fullmatch(
            r"/api/v1/chats(?:/[^/]+/messages(?:/[^/]+/retries)?)?", path
        ):
            raise ValueError("fixture_security_analysis_denied")
    return dispatch(item, client, service, deliver, captured, analysis)
