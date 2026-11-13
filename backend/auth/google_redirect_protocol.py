"""Bounded GIS request parsing and unambiguous double-submit cookies."""

import json
import re
from urllib.parse import parse_qsl
from fastapi import HTTPException, Request
from auth.security import tokens_match
from nl2sql.config import Settings

MAX_BYTES = 16384


def cookie(request: Request, name: str) -> str:
    # Ambiguous duplicate cookies cannot choose the CSRF/challenge authority.
    values = []
    for header in request.headers.getlist("cookie"):
        if len(header) > MAX_BYTES:
            raise HTTPException(403, "Start a new sign-in attempt.")
        for part in header.split(";"):
            key, separator, value = part.strip().partition("=")
            if separator and key == name:
                if len(value) > 512:
                    raise HTTPException(403, "Start a new sign-in attempt.")
                values.append(value)
    if len(values) > 1:
        raise HTTPException(403, "Start a new sign-in attempt.")
    return values[0] if values else ""


def pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError("duplicate_field")
        value[key] = item
    return value


async def payload(request: Request, settings: Settings) -> dict[str, str]:
    if request.url.query:
        raise HTTPException(400, "Start a new sign-in attempt.")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > MAX_BYTES:
            raise HTTPException(413, "Request is too large.")
        raw.extend(chunk)
    kind = request.headers.get("content-type", "").split(";", 1)[0].lower()
    try:
        if kind == "application/json":
            body = json.loads(raw, object_pairs_hook=pairs)
        elif kind == "application/x-www-form-urlencoded":
            text = raw.decode("ascii")
            if re.search(r"%(?![0-9A-Fa-f]{2})", text):
                raise ValueError("encoding_invalid")
            body = pairs(
                parse_qsl(
                    text,
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=3,
                    errors="strict",
                )
            )
        else:
            raise ValueError("content_type_invalid")
        if (
            not isinstance(body, dict)
            or set(body)
            not in (
                {"credential", "g_csrf_token"},
                {"credential", "g_csrf_token", "client_id"},
            )
            or not all(isinstance(value, str) for value in body.values())
        ):
            raise ValueError("fields_invalid")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,8192}", body["credential"]):
            raise ValueError("credential_invalid")
        token = body["g_csrf_token"]
        if not 1 <= len(token) <= 512 or any(
            not 33 <= ord(char) <= 126 or char in ';,"\\' for char in token
        ):
            raise ValueError("csrf_invalid")
        if (
            body.get("client_id", settings.google_client_id)
            != settings.google_client_id
        ):
            raise ValueError("client_invalid")
        return body
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise HTTPException(400, "Start a new sign-in attempt.") from None


def google_csrf(
    request: Request, body: dict[str, str], *, required: bool = True
) -> None:
    actual = cookie(request, "g_csrf_token")
    if (actual or required) and (
        not actual or not tokens_match(actual, body["g_csrf_token"])
    ):
        raise HTTPException(403, "Start a new sign-in attempt.")
