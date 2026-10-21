"""Fresh database identity/grant checks precede all private application work."""

import hmac
from dataclasses import dataclass
from typing import Any
from fastapi import Depends, HTTPException, Request
from auth.accounts import validate_identity
from auth.config import AuthDenied, load_auth_policy
from auth.sessions import bound_value, read_token, session_cookie_name, token_digest
from auth.store import IdentityStore
from nl2sql.config import Settings
from storage.pool import StorageUnavailable


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def ensure_configured(settings: Settings, *, google: bool = False) -> None:
    if len(settings.session_secret) < 32:
        raise HTTPException(503, "Authentication is temporarily unavailable.")
    if google and not settings.google_client_id:
        raise HTTPException(503, "Google sign-in is not configured.")


def get_store(
    request: Request, settings: Settings = Depends(get_settings)
) -> IdentityStore:
    ensure_configured(settings)
    if not request.app.state.storage.settings.enabled:
        raise HTTPException(503, "Authentication is temporarily unavailable.")
    try:
        policy = load_auth_policy(settings)
    except ValueError:
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    return IdentityStore(request.app.state.storage, policy)


def tokens_match(actual: str, expected: str) -> bool:
    return hmac.compare_digest(actual.encode("utf-8"), expected.encode("utf-8"))


def check_csrf(request: Request, expected: str) -> None:
    if request.headers.get("origin") != get_settings(request).app_origin:
        raise HTTPException(403, "Request origin is not allowed.")
    actual = request.headers.get("x-csrf-token", "")
    if (
        not actual
        or not expected
        or len(actual) > 256
        or not tokens_match(actual, expected)
    ):
        raise HTTPException(403, "Invalid CSRF token.")


def identity_from_claims(claims: dict[str, Any]) -> dict[str, Any]:
    validate_identity(claims)
    identity = {
        key: claims.get(key, "") for key in ("sub", "email", "name", "picture", "hd")
    }
    identity.update(
        email=claims["email"].lower(),
        email_verified=True,
        iss="https://accounts.google.com",
    )
    return identity


def public_identity(identity: dict[str, Any]) -> dict[str, str]:
    return {key: identity[key] for key in ("id", "email", "name", "picture")}


@dataclass(frozen=True)
class UserSession:
    user: dict[str, Any]
    csrf_token: str
    token_digest: bytes = b""
    can_query: bool = False
    grant_version: int = 0
    auth_epoch: int = 0
    dataset_key: str = ""


def require_user(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
) -> UserSession:
    token = read_token(request.cookies.get(session_cookie_name(settings)))
    if token is None:
        raise HTTPException(401, "Sign in to continue.")
    csrf = bound_value(settings, token, "session-csrf")
    meaningful = request.method not in {"GET", "HEAD", "OPTIONS"}
    # Invalid cross-site actions must not extend idle lifetime or consume SQL.
    if meaningful:
        check_csrf(request, csrf)
    try:
        stored = store.authenticate(token_digest(token), meaningful_activity=meaningful)
    except AuthDenied:
        raise HTTPException(401, "Sign in to continue.") from None
    except StorageUnavailable:
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    if not hmac.compare_digest(stored.csrf_digest, token_digest(csrf)):
        raise HTTPException(401, "Sign in to continue.")
    return UserSession(
        stored.user,
        csrf,
        token_digest(token),
        stored.can_query,
        stored.grant_version,
        stored.auth_epoch,
        stored.dataset_key,
    )


def require_database_access(
    session: UserSession = Depends(require_user),
) -> UserSession:
    if not session.can_query:
        raise HTTPException(403, "This account cannot query the database.")
    return session
