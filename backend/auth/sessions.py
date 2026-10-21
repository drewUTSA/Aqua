"""Opaque v2 cookies; database digests and server-bound CSRF replace signed claims."""

import base64
import hashlib
import hmac
import re
import secrets

from fastapi import Response

from nl2sql.config import Settings

LOGIN_MAX_AGE_SECONDS = 600


def challenge_cookie_name(settings: Settings) -> str:
    """Use a host-bound cookie on HTTPS and a separate name for local HTTP."""
    return _cookie_name(settings, "login")


def session_cookie_name(settings: Settings) -> str:
    """Prevent production cookies from being shared with unrelated subdomains."""
    return _cookie_name(settings, "session")


def _cookie_name(settings: Settings, kind: str) -> str:
    prefix = "__Host-" if settings.app_origin.startswith("https://") else ""
    return f"{prefix}aqua_{kind}"


def new_token() -> str:
    return "v2." + secrets.token_urlsafe(32)


def read_token(value: str | None) -> str | None:
    """Legacy signed cookies deliberately have no fallback acceptance path."""
    return (
        value
        if isinstance(value, str) and re.fullmatch(r"v2\.[A-Za-z0-9_-]{43}", value)
        else None
    )


def token_digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def bound_value(settings: Settings, token: str, purpose: str) -> str:
    """Recover nonce/CSRF without persisting plaintext reusable browser secrets."""
    message = ("aqua-v2:" + purpose + ":" + token).encode("utf-8")
    value = hmac.new(
        settings.session_secret.encode("utf-8"), message, hashlib.sha256
    ).digest()
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def set_auth_cookie(
    response: Response, settings: Settings, name: str, value: str, max_age: int
) -> None:
    """Cookies remain inaccessible to JavaScript and confined to this host."""
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=settings.app_origin.startswith("https://"),
        httponly=True,
        samesite="lax",
    )


def clear_auth_cookie(response: Response, settings: Settings, name: str) -> None:
    """Match the original cookie attributes when removing it."""
    response.delete_cookie(
        name,
        path="/",
        secure=settings.app_origin.startswith("https://"),
        httponly=True,
        samesite="lax",
    )
