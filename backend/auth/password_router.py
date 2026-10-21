"""Anonymous password endpoints preserve the existing Google/session facade."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from auth.password_bootstrap import Action, consume, cookie_name, issue, peer
from auth.password_errors import execute, log
from auth.password_settings import check_action, get_password_store
from auth.passwords import PasswordStore
from auth.security import get_settings, public_identity
from auth.sessions import (
    bound_value,
    clear_auth_cookie,
    new_token,
    session_cookie_name,
    set_auth_cookie,
    token_digest,
)
from nl2sql.config import Settings

router = APIRouter(prefix="/api/v1/auth", tags=["password authentication"])
ACK = {"detail": "If this address is eligible, account instructions will be sent."}
CurrentSettings = Annotated[Settings, Depends(get_settings)]
PasswordService = Annotated[PasswordStore, Depends(get_password_store)]


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(min_length=3, max_length=254)


class PasswordCredential(EmailRequest):
    password: str = Field(min_length=1, max_length=512)


class EmailProof(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=43, max_length=43)
    password: str = Field(min_length=1, max_length=512)


def _start(
    action: Action, request: Request, settings: Settings, store: PasswordStore
) -> None:
    check_action(action)
    execute("bootstrap", lambda: consume(action, request, settings, store))


@router.get("/bootstrap")
def bootstrap(
    action: Action,
    request: Request,
    response: Response,
    settings: CurrentSettings,
    store: PasswordService,
) -> dict[str, Any]:
    check_action(action)
    csrf = execute(
        "bootstrap", lambda: issue(action, request, response, settings, store)
    )
    return {
        "csrf_token": csrf,
        "capabilities": {
            "google_login": bool(settings.google_client_id),
            "password_login": True,
            "durable_sessions": True,
        },
        "password_policy": {
            "minimum_length": 15,
            "maximum_length": 128,
            "normalization": "NFC",
        },
    }


@router.post("/registrations", status_code=202)
def registration(
    body: EmailRequest,
    request: Request,
    response: Response,
    settings: CurrentSettings,
    store: PasswordService,
) -> dict[str, str]:
    _start("registration", request, settings, store)
    execute(
        "registration",
        lambda: store.request_email(body.email, "verify_email", peer(request)),
    )
    clear_auth_cookie(response, settings, cookie_name(settings))
    log.info("password_event action=allow reason=registration_requested")
    return ACK


@router.post("/email-verifications", status_code=204)
def verification(
    body: EmailProof,
    request: Request,
    response: Response,
    settings: CurrentSettings,
    store: PasswordService,
) -> None:
    _start("verification", request, settings, store)
    execute(
        "verification",
        lambda: store.complete_verification(body.token, body.password, peer(request)),
    )
    clear_auth_cookie(response, settings, cookie_name(settings))
    log.info("password_event action=allow reason=email_verified")


@router.post("/password-login")
def login(
    body: PasswordCredential,
    request: Request,
    response: Response,
    settings: CurrentSettings,
    store: PasswordService,
) -> dict[str, Any]:
    _start("login", request, settings, store)
    token = new_token()
    csrf = bound_value(settings, token, "session-csrf")
    stored = execute(
        "login",
        lambda: store.login(
            body.email,
            body.password,
            token_digest(token),
            token_digest(csrf),
            peer(request),
            settings,
        ),
    )
    set_auth_cookie(
        response,
        settings,
        session_cookie_name(settings),
        token,
        settings.session_max_age_seconds,
    )
    clear_auth_cookie(response, settings, cookie_name(settings))
    log.info("password_event action=allow reason=session_created")
    return {
        "user": public_identity(stored.user),
        "csrf_token": csrf,
        "can_query": stored.can_query,
        "capabilities": {
            "google_login": bool(settings.google_client_id),
            "password_login": True,
            "durable_sessions": True,
        },
    }


@router.post("/password-reset-requests", status_code=202)
def reset_request(
    body: EmailRequest,
    request: Request,
    response: Response,
    settings: CurrentSettings,
    store: PasswordService,
) -> dict[str, str]:
    _start("reset-request", request, settings, store)
    execute(
        "reset-request",
        lambda: store.request_email(body.email, "password_reset", peer(request)),
    )
    clear_auth_cookie(response, settings, cookie_name(settings))
    log.info("password_event action=allow reason=reset_requested")
    return ACK


@router.post("/password-resets", status_code=204)
def reset(
    body: EmailProof,
    request: Request,
    response: Response,
    settings: CurrentSettings,
    store: PasswordService,
) -> None:
    _start("reset", request, settings, store)
    execute(
        "reset", lambda: store.reset_password(body.token, body.password, peer(request))
    )
    clear_auth_cookie(response, settings, cookie_name(settings))
    clear_auth_cookie(response, settings, session_cookie_name(settings))
    log.info("password_event action=allow reason=password_reset")
