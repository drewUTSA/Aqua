"""Browser-bound one-use Google challenges and durable session lifecycle."""

from typing import Any
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from google.auth.exceptions import GoogleAuthError, TransportError
from pydantic import BaseModel, Field
from auth.config import AuthDenied, AuthLimited
from auth.google import verify_google_token
from auth.security import (
    UserSession,
    check_csrf,
    ensure_configured,
    get_settings,
    get_store,
    identity_from_claims,
    public_identity,
    require_user,
    tokens_match,
)
from auth.sessions import (
    bound_value,
    challenge_cookie_name,
    clear_auth_cookie,
    new_token,
    read_token,
    session_cookie_name,
    set_auth_cookie,
    token_digest,
)
from auth.store import IdentityStore
from nl2sql.config import Settings
from storage.pool import StorageUnavailable

router = APIRouter(prefix="/api/auth", tags=["authentication"])
log = logging.getLogger("aqua.auth")


class GoogleCredential(BaseModel):
    credential: str = Field(min_length=1, max_length=8192)


def _capabilities(settings: Settings) -> dict[str, bool]:
    return {
        "google_login": bool(settings.google_client_id),
        "password_login": False,
        "durable_sessions": True,
    }


def _session_response(session: UserSession, settings: Settings) -> dict[str, Any]:
    return {
        "user": public_identity(session.user),
        "csrf_token": session.csrf_token,
        "can_query": session.can_query,
        "capabilities": _capabilities(settings),
    }


def _limited(error: AuthLimited) -> HTTPException:
    return HTTPException(
        429,
        "Too many sign-in attempts. Try again shortly.",
        headers={"Retry-After": str(error.retry_after)},
    )


def _peer(request: Request) -> str:
    # Forged forwarding headers never create a budget. The current tunnel peer
    # is intentionally aggregate until a separately reviewed ingress trust chain.
    return request.client.host if request.client else "unknown"


@router.get("/config")
def login_config(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
) -> dict[str, Any]:
    ensure_configured(settings, google=True)
    token = new_token()
    csrf = bound_value(settings, token, "login-csrf")
    try:
        store.issue_challenge(token_digest(token), token_digest(csrf), _peer(request))
    except AuthLimited as error:
        raise _limited(error) from None
    except StorageUnavailable:
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    set_auth_cookie(
        response,
        settings,
        challenge_cookie_name(settings),
        token,
        store.policy.challenge_seconds,
    )
    return {
        "client_id": settings.google_client_id,
        "nonce": bound_value(settings, token, "google-nonce"),
        "csrf_token": csrf,
        "capabilities": _capabilities(settings),
    }


@router.post("/google")
def google_login(
    body: GoogleCredential,
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
) -> dict[str, Any]:
    ensure_configured(settings, google=True)
    challenge = read_token(request.cookies.get(challenge_cookie_name(settings)))
    if challenge is None:
        raise HTTPException(403, "Start a new sign-in attempt.")
    csrf = bound_value(settings, challenge, "login-csrf")
    check_csrf(request, csrf)
    try:
        store.consume_challenge(token_digest(challenge), token_digest(csrf))
        store.reserve_login(_peer(request))
    except AuthDenied:
        log.warning("auth_event action=deny reason=challenge_invalid")
        raise HTTPException(403, "Start a new sign-in attempt.") from None
    except AuthLimited as error:
        log.warning("auth_event action=deny reason=callback_rate_limited")
        raise _limited(error) from None
    except StorageUnavailable:
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    # Consumption/admission commit before verification. No DB lease is held
    # during network I/O, and provider failure cannot replay the same challenge.
    try:
        claims = verify_google_token(body.credential, settings.google_client_id)
        nonce = claims.get("nonce")
        if not isinstance(nonce, str) or not tokens_match(
            nonce, bound_value(settings, challenge, "google-nonce")
        ):
            raise ValueError("invalid_nonce")
        identity = identity_from_claims(claims)
    except TransportError:
        log.warning("auth_event action=deny reason=provider_unavailable")
        raise HTTPException(
            503,
            "Google sign-in is temporarily unavailable. Start a new sign-in attempt.",
        ) from None
    except (ValueError, GoogleAuthError, AuthDenied):
        log.warning("auth_event action=deny reason=identity_invalid")
        raise HTTPException(401, "Google sign-in could not be verified.") from None
    token = new_token()
    session_csrf = bound_value(settings, token, "session-csrf")
    try:
        stored = store.login(
            identity,
            token_digest(token),
            token_digest(session_csrf),
            _peer(request),
            settings,
        )
    except AuthDenied:
        log.warning("auth_event action=deny reason=account_invalid")
        raise HTTPException(401, "Google sign-in could not be completed.") from None
    except AuthLimited as error:
        log.warning("auth_event action=deny reason=account_rate_limited")
        raise _limited(error) from None
    except StorageUnavailable:
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    set_auth_cookie(
        response,
        settings,
        session_cookie_name(settings),
        token,
        settings.session_max_age_seconds,
    )
    log.info("auth_event action=allow reason=session_created")
    clear_auth_cookie(response, settings, challenge_cookie_name(settings))
    session = UserSession(
        stored.user,
        session_csrf,
        token_digest(token),
        stored.can_query,
        stored.grant_version,
        stored.auth_epoch,
        stored.dataset_key,
    )
    return _session_response(session, settings)


@router.get("/me")
def current_user(
    session: UserSession = Depends(require_user),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    return _session_response(session, settings)


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session: UserSession = Depends(require_user),
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
) -> None:
    try:
        store.revoke(session.token_digest)
    except StorageUnavailable:
        # No success response or cookie deletion until durable revocation commits.
        log.warning("auth_event action=deny reason=logout_unavailable")
        raise HTTPException(
            503, "Sign out could not be completed. Try again."
        ) from None
    clear_auth_cookie(response, settings, session_cookie_name(settings))
    clear_auth_cookie(response, settings, challenge_cookie_name(settings))
    log.info("auth_event action=allow reason=session_revoked")
