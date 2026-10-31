"""Explicit same-origin identity actions, separate from preference persistence."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response

from account import notifications
from account.action_contracts import ActionProof
from account.google_methods import GoogleMethods
from account.google_reauth import GoogleRecentAuth
from account.identity_contracts import (
    EmailCompletion,
    EmailRequest,
    GoogleCandidate,
    GoogleChallenge,
    GoogleLink,
    GoogleVerification,
    NotificationUpdate,
    PasswordEnrollment,
)
from account.identity_runtime import action_target, get_identity_passwords
from account.mail_actions import MailActions
from account.policy import identifier
from account.security_http import binding_cookie, identity_cookie, perform
from account.security_router import clear_current, closed_query
from auth.passwords import PasswordStore
from auth.security import UserSession, get_settings, get_store, require_user
from auth.sessions import new_token, read_token, set_auth_cookie, token_digest
from auth.store import IdentityStore
from nl2sql.config import Settings
from workspace.errors import WorkspaceError

router = APIRouter(prefix="/api/v1/me", tags=["private identity actions"])
Session = Annotated[UserSession, Depends(require_user)]
Passwords = Annotated[PasswordStore, Depends(get_identity_passwords)]
Config = Annotated[Settings, Depends(get_settings)]
Store = Annotated[IdentityStore, Depends(get_store)]


def binding(request, settings, *, identity=False):
    return (
        read_token(
            request.cookies.get(
                identity_cookie(settings) if identity else binding_cookie(settings)
            )
        )
        or ""
    )


@router.post("/reauth/google-challenges")
def start_google(
    body: GoogleChallenge,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        token, cookie = new_token(), new_token()
        result = GoogleRecentAuth(passwords, settings).start(
            session,
            body.operation,
            action_target(session, body),
            body.identity_id,
            token,
            cookie,
        )
        set_auth_cookie(response, settings, binding_cookie(settings), cookie, 300)
        return result

    return perform("google_challenge", work)


@router.post("/reauth/google")
def verify_google(
    body: GoogleVerification,
    request: Request,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        return GoogleRecentAuth(passwords, settings).verify(
            session,
            body.operation,
            action_target(session, body),
            body.challenge_id,
            body.challenge_token,
            binding(request, settings),
            body.credential,
        )

    return perform("google_reauth", work)


@router.post("/google-link-challenges")
def start_link(
    body: ActionProof,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        token, cookie = new_token(), new_token()
        result = GoogleMethods(passwords, settings).start(
            session, token_digest(body.proof_token), token, cookie
        )
        set_auth_cookie(response, settings, identity_cookie(settings), cookie, 300)
        return result

    return perform("google_link_challenge", work)


@router.post("/google-link-candidates")
def verify_link(
    body: GoogleCandidate,
    request: Request,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        return GoogleMethods(passwords, settings).candidate(
            session,
            body.challenge_id,
            body.challenge_token,
            binding(request, settings, identity=True),
            body.credential,
        )

    return perform("google_link_candidate", work)


@router.post("/google-links")
def link(
    body: GoogleLink,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        result = GoogleMethods(passwords, settings).link(
            session,
            token_digest(body.proof_token),
            token_digest(body.candidate_token),
            token_digest(binding(request, settings, identity=True)),
        )
        clear_current(response, settings)
        return result

    return perform("google_link", work)


@router.post("/methods/google/{identity_id}/revocations")
def unlink(
    identity_id: str,
    body: ActionProof,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        try:
            target = identifier(identity_id)
        except ValueError:
            raise WorkspaceError("invalid_request", 422) from None
        result = GoogleMethods(passwords, settings).unlink(
            session, target, token_digest(body.proof_token)
        )
        clear_current(response, settings)
        return result

    return perform("google_unlink", work)


def mail_start(operation, body, request, response, session, passwords, settings):
    closed_query(request)
    token, cookie = new_token(), new_token()
    result = MailActions(passwords).start(
        session,
        operation,
        token_digest(body.proof_token),
        token_digest(token),
        token_digest(cookie),
        getattr(body, "new_email", None),
    )
    set_auth_cookie(response, settings, identity_cookie(settings), cookie, 1800)
    return {**result, "request_token": token}


@router.post("/password-enrollments")
def start_password(
    body: ActionProof,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    return perform(
        "password_enrollment",
        lambda: mail_start(
            "password_add", body, request, response, session, passwords, settings
        ),
    )


@router.post("/password")
def add_password(
    body: PasswordEnrollment,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        result = MailActions(passwords).add_password(
            session, body, token_digest(binding(request, settings, identity=True))
        )
        clear_current(response, settings)
        return result

    return perform("password_add", work)


@router.post("/email-change-requests")
def start_email(
    body: EmailRequest,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    return perform(
        "email_change_request",
        lambda: mail_start(
            "email_change", body, request, response, session, passwords, settings
        ),
    )


@router.put("/email")
def change_email(
    body: EmailCompletion,
    request: Request,
    response: Response,
    session: Session,
    passwords: Passwords,
    settings: Config,
):
    def work():
        closed_query(request)
        result = MailActions(passwords).change_email(
            session, body, token_digest(binding(request, settings, identity=True))
        )
        clear_current(response, settings)
        return result

    return perform("email_change", work)


@router.get("/notification-settings")
def read_notifications(request: Request, session: Session, store: Store):
    def work():
        closed_query(request)
        return notifications.execute(store, session)

    return perform("notifications_read", work)


@router.put("/notification-settings")
def save_notifications(
    body: NotificationUpdate, request: Request, session: Session, store: Store
):
    def work():
        closed_query(request)
        return notifications.execute(store, session, body)

    return perform("notifications_save", work)
