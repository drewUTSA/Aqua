"""Opt-in GIS redirect transport; the existing login owns every auth mutation."""

import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse
from starlette.concurrency import run_in_threadpool

from auth.security import ensure_configured, get_settings, get_store
from auth.sessions import bound_value, challenge_cookie_name, read_token
from auth.store import IdentityStore
from auth.google_redirect_bridge import document
from auth.google_redirect_protocol import cookie, payload, google_csrf
from nl2sql.config import Settings

router = APIRouter(prefix="/google", tags=["authentication"])
PATH = "/api/auth/google/redirect"


def redirect_path(settings: Settings) -> str | None:
    if os.environ.get("GOOGLE_REDIRECT_ENABLED", "false") != "true":
        return None
    if not settings.app_origin.startswith("https://"):
        raise HTTPException(503, "Google sign-in is temporarily unavailable.")
    return PATH


def enabled(settings: Settings) -> None:
    if redirect_path(settings) is None:
        raise HTTPException(404, "Not found.")
    ensure_configured(settings, google=True)


@router.post("/redirect", response_class=HTMLResponse)
async def landing(request: Request, settings: Settings = Depends(get_settings)):
    enabled(settings)
    if request.headers.get("origin") not in {
        None,
        settings.app_origin,
        "https://accounts.google.com",
    }:
        raise HTTPException(403, "Request origin is not allowed.")
    body = await payload(request, settings)
    # A top-level cross-site POST may omit Lax cookies. This document makes no
    # auth mutation: both CSRF checks and the original challenge are required
    # on its subsequent first-party completion, without weakening any cookie.
    google_csrf(request, body, required=False)
    html, headers = document(body)
    return HTMLResponse(html, headers=headers)


@router.get("/redirect-state")
def state(request: Request, settings: Settings = Depends(get_settings)):
    enabled(settings)
    if request.headers.get("origin") not in {None, settings.app_origin}:
        raise HTTPException(403, "Request origin is not allowed.")
    challenge = read_token(cookie(request, challenge_cookie_name(settings)))
    if not challenge or not cookie(request, "g_csrf_token"):
        raise HTTPException(403, "Start a new sign-in attempt.")
    return {"csrf_token": bound_value(settings, challenge, "login-csrf")}


@router.post("/redirect-complete")
async def complete(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
):
    enabled(settings)
    body = await payload(request, settings)
    google_csrf(request, body)
    cookie(request, challenge_cookie_name(settings))
    # Reuse the original Origin/header-CSRF, consume-before-provider, nonce,
    # verifier, account allowlist, durable login and grant checks unchanged.
    from auth.router import GoogleCredential, google_login

    return await run_in_threadpool(
        google_login,
        GoogleCredential(credential=body["credential"]),
        request,
        response,
        settings,
        store,
    )
