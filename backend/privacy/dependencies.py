"""Download GET pairs the current cookie/CSRF before authentication SQL."""

import threading
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from auth.security import get_settings, get_store, require_user, tokens_match
from auth.sessions import bound_value, read_token, session_cookie_name
from nl2sql.config import Settings
from privacy.service import ExportService
from auth.store import IdentityStore

LOCK = threading.Lock()


def get_service(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
) -> ExportService:
    with LOCK:
        service = getattr(request.app.state, "privacy", None)
        if (
            service is not None
            and service.storage is store.storage
            and service.settings == settings
        ):
            return service
        # Configuration is immutable for a normal app lifecycle. Do not drop a
        # live async download pool merely to replace a fixture/config generation.
        if service is not None:
            # Only the owning lifespan may drain an async pool. A changed
            # configuration must not create another generation of physical
            # connections while the former one still serves a stream.
            raise HTTPException(503, "Export service unavailable.")
        service = ExportService(store.storage, store.policy, settings, start=True)
        request.app.state.privacy = service
        return service


def download_session(
    request: Request,
    settings: Settings = Depends(get_settings),
    store: IdentityStore = Depends(get_store),
):
    for name in (
        "x-csrf-token",
        "origin",
        "sec-fetch-site",
        "sec-fetch-mode",
        "sec-fetch-dest",
        "content-length",
        "purpose",
        "sec-purpose",
    ):
        if len(request.headers.getlist(name)) > 1:
            raise HTTPException(403, "Invalid export request.")
    if (
        any(
            name in request.headers
            for name in ("transfer-encoding", "range", "if-range")
        )
        or request.headers.get("content-length", "0") != "0"
        or request.headers.get("sec-fetch-mode") not in {None, "cors", "same-origin"}
        or request.headers.get("sec-fetch-dest", "empty") not in {"", "empty"}
        or any(name in request.headers for name in ("purpose", "sec-purpose"))
    ):
        raise HTTPException(403, "Invalid export request.")
    raw = read_token(request.cookies.get(session_cookie_name(settings)))
    if raw is None:
        raise HTTPException(401, "Sign in to continue.")
    expected = bound_value(settings, raw, "session-csrf")
    supplied = request.headers.get("x-csrf-token", "")
    origin = request.headers.get("origin")
    site = request.headers.get("sec-fetch-site")
    if (
        len(supplied) > 128
        or not tokens_match(supplied, expected)
        or origin is not None
        and origin != settings.app_origin
        or site is not None
        and site not in {"same-origin", "none"}
    ):
        raise HTTPException(403, "Invalid CSRF token.")
    if request.query_params:
        raise HTTPException(422, "Invalid export request.")
    # require_user's GET path does not extend idle lifetime. Header pairing above
    # prevents cookie-B/CSRF-A from reaching that first authentication SQL call.
    return require_user(request, settings, store)


Service = Annotated[ExportService, Depends(get_service)]
