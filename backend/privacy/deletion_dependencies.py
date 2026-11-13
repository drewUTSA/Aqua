"""An explicit receipt can acknowledge only its original deletion, never data."""

from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from auth.security import check_csrf, ensure_configured, get_settings
from auth.sessions import bound_value, read_token, session_cookie_name, token_digest
from nl2sql.config import Settings
from auth.security import get_store
from auth.store import IdentityStore
from privacy.deletion_service import Deletions


@dataclass(frozen=True)
class DeletionBearer:
    digest: bytes = field(repr=False)
    csrf: str = field(repr=False)


def bearer(request: Request, settings: Settings = Depends(get_settings)):
    ensure_configured(settings)
    for name in ("cookie", "origin", "x-csrf-token", "x-aqua-deletion-receipt"):
        if len(request.headers.getlist(name)) > 1:
            raise HTTPException(403, "Invalid deletion request.")
    cookie_name = session_cookie_name(settings)
    names = [
        part.partition("=")[0].strip()
        for part in request.headers.get("cookie", "").split(";")
    ]
    if names.count(cookie_name) != 1:
        raise HTTPException(401, "Sign in to continue.")
    raw = read_token(request.cookies.get(cookie_name))
    if raw is None:
        raise HTTPException(401, "Sign in to continue.")
    csrf = bound_value(settings, raw, "session-csrf")
    check_csrf(request, csrf)
    if request.query_params or request.headers.get("sec-fetch-site") not in {
        None,
        "same-origin",
        "none",
    }:
        raise HTTPException(403, "Invalid deletion request.")
    return DeletionBearer(token_digest(raw), csrf)


Bearer = Annotated[DeletionBearer, Depends(bearer)]


def get_service(request: Request, store: IdentityStore = Depends(get_store)):
    service = getattr(request.app.state, "deletions", None)
    if service is None or service.storage is not store.storage:
        raise HTTPException(503, "Deletion service unavailable.")
    return service


Service = Annotated[Deletions, Depends(get_service)]
