"""Separate method availability: pausing signups must not lock out existing users."""

import os

from fastapi import Depends, HTTPException, Request

from auth.mailconfig import MailPolicy, MailUnavailable, load_mail_policy
from auth.password_policy import PasswordPolicy
from auth.passwords import PasswordStore
from auth.security import get_settings, get_store
from auth.store import IdentityStore
from nl2sql.config import Settings


def feature(name: str) -> bool:
    value = os.environ.get(name, "false")
    if value not in {"true", "false"}:
        raise HTTPException(503, "Password authentication is temporarily unavailable.")
    return value == "true"


def check_action(action: str) -> None:
    if not feature("PASSWORD_AUTH_ENABLED"):
        raise HTTPException(503, "Password authentication is temporarily unavailable.")
    gate = {
        "registration": "PASSWORD_REGISTRATION_ENABLED",
        "reset-request": "PASSWORD_RECOVERY_ENABLED",
    }.get(action)
    if gate and not feature(gate):
        raise HTTPException(
            503, "This authentication action is temporarily unavailable."
        )


def get_password_store(
    request: Request,
    settings: Settings = Depends(get_settings),
    identity: IdentityStore = Depends(get_store),
) -> PasswordStore:
    check_action("login")
    try:
        policy = PasswordPolicy(
            verification_seconds=int(
                os.environ.get("PASSWORD_VERIFICATION_SECONDS", "86400")
            ),
            reset_seconds=int(os.environ.get("PASSWORD_RESET_SECONDS", "1800")),
        )
    except (ValueError, TypeError):
        raise HTTPException(
            503, "Password authentication is temporarily unavailable."
        ) from None
    try:
        mail = load_mail_policy()
        if mail.public_origin.rstrip("/") != settings.app_origin:
            raise MailUnavailable("account_mail_origin_mismatch")
    except MailUnavailable:
        # A broken mail integration cannot disable valid password sessions/login.
        mail = MailPolicy()
    return PasswordStore(request.app.state.storage, identity.policy, policy, mail)
