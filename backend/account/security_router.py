"""Authenticated account actions; anonymous login/recovery are not proof issuers."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request, Response

from account.action_contracts import (
    ActionProof,
    ActionTarget,
    PasswordChange,
    PasswordReauth,
)
from account.policy import PROOF_SECONDS, identifier
from account.reauth import RecentAuth
from account.security_actions import SecurityActions
from account.security_http import binding_cookie, perform
from auth.password_settings import get_password_store
from auth.passwords import PasswordStore
from auth.security import UserSession, get_settings, require_user
from auth.sessions import (
    challenge_cookie_name,
    clear_auth_cookie,
    new_token,
    read_token,
    session_cookie_name,
    set_auth_cookie,
    token_digest,
)
from nl2sql.config import Settings
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me", tags=["private account security"])
Session = Annotated[UserSession, Depends(require_user)]
Passwords = Annotated[PasswordStore, Depends(get_password_store)]
Config = Annotated[Settings, Depends(get_settings)]


def closed_query(request: Request) -> None:
    if request.query_params:
        raise WorkspaceError("invalid_request", 422)


def clear_current(response: Response, settings: Settings) -> None:
    for name in (
        session_cookie_name(settings),
        challenge_cookie_name(settings),
        binding_cookie(settings),
    ):
        clear_auth_cookie(response, settings, name)


@router.post("/reauth-challenges")
def start_challenge(
    body: ActionTarget,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
) -> Any:
    def work() -> dict:
        closed_query(request)
        token, binding = new_token(), new_token()
        result = RecentAuth(passwords).start(
            session,
            body.operation,
            body.target_session_id,
            token_digest(token),
            token_digest(binding),
        )
        set_auth_cookie(
            response, settings, binding_cookie(settings), binding, PROOF_SECONDS
        )
        return {**result, "challenge_token": token}

    return perform("challenge", work)


@router.post("/reauth/password")
def verify_password(
    body: PasswordReauth,
    request: Request,
    session: Session,
    passwords: Passwords,
    settings: Config,
) -> Any:
    def work() -> dict:
        closed_query(request)
        binding = read_token(request.cookies.get(binding_cookie(settings)))
        # An absent/mismatched binding still spends claim admission but cannot
        # match a real random digest or reach Argon2 verification.
        return RecentAuth(passwords).password(
            session,
            body.challenge_id,
            body.operation,
            body.target_session_id,
            token_digest(body.challenge_token),
            token_digest(binding or ""),
            body.password,
        )

    return perform("reauth", work)


@router.put("/password")
def change_password(
    body: PasswordChange,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
) -> Any:
    def work() -> dict:
        closed_query(request)
        result = SecurityActions(passwords).password(
            session, token_digest(body.proof_token), body.new_password
        )
        clear_current(response, settings)
        return result

    return perform("password_change", work)


@router.post("/sessions/{session_id}/revocations")
def revoke_session(
    session_id: str,
    body: ActionProof,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
) -> Any:
    def work() -> dict:
        closed_query(request)
        try:
            target = identifier(session_id)
        except ValueError:
            raise WorkspaceError("invalid_request", 422) from None
        result = SecurityActions(passwords).session(
            session, target, token_digest(body.proof_token)
        )
        if result["current_session_revoked"]:
            clear_current(response, settings)
        return result

    return perform("session_revoke", work)


@router.post("/session-revocations")
def revoke_sessions(
    body: ActionProof,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
) -> Any:
    def work() -> dict:
        closed_query(request)
        result = SecurityActions(passwords).session(
            session, None, token_digest(body.proof_token)
        )
        clear_current(response, settings)
        return result

    return perform("sessions_revoke_all", work)
