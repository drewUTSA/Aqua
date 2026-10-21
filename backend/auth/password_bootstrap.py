"""Single-use anonymous actions, independent of Google provider configuration."""

from typing import Literal

from fastapi import HTTPException, Request, Response

from auth.admission import admit, cleanup
from auth.config import AuthDenied
from auth.security import check_csrf
from auth.sessions import (
    bound_value,
    new_token,
    read_token,
    set_auth_cookie,
    token_digest,
)
from auth.passwords import PasswordStore
from nl2sql.config import Settings

Action = Literal["registration", "verification", "login", "reset-request", "reset"]


def cookie_name(settings: Settings) -> str:
    return (
        "__Host-aqua_password"
        if settings.app_origin.startswith("https://")
        else "aqua_password"
    )


def peer(request: Request) -> str:
    # Never let forwarding headers or browser identifiers create a fresh quota.
    return request.client.host if request.client else "unknown"


def issue(
    action: Action,
    request: Request,
    response: Response,
    settings: Settings,
    store: PasswordStore,
) -> str:
    token = new_token()
    csrf = bound_value(settings, token, f"password-{action}-csrf")
    with store.storage.transaction() as conn:
        admit(conn, store.auth_policy, "challenge", peer(request))
        cleanup(conn, store.auth_policy)
        conn.execute(
            "INSERT INTO app.auth_challenges(purpose,secret_digest,binding_digest,expires_at) "
            "VALUES ('password_action',%s,%s,now()+%s*interval '1 second')",
            (
                token_digest(token),
                token_digest(csrf),
                store.auth_policy.challenge_seconds,
            ),
        )
    set_auth_cookie(
        response,
        settings,
        cookie_name(settings),
        token,
        store.auth_policy.challenge_seconds,
    )
    return csrf


def consume(
    action: Action, request: Request, settings: Settings, store: PasswordStore
) -> None:
    token = read_token(request.cookies.get(cookie_name(settings)))
    if token is None:
        raise HTTPException(403, "Start a new authentication attempt.")
    csrf = bound_value(settings, token, f"password-{action}-csrf")
    check_csrf(request, csrf)
    with store.storage.transaction() as conn:
        row = conn.execute(
            "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() "
            "WHERE purpose='password_action' AND secret_digest=%s AND binding_digest=%s "
            "AND consumed_at IS NULL AND expires_at>clock_timestamp() RETURNING id",
            (token_digest(token), token_digest(csrf)),
        ).fetchone()
        if row is None:
            raise AuthDenied("password_bootstrap_invalid")
