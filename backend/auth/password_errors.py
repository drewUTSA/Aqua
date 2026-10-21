"""Fixed action/reason events and public errors never include submitted values."""

from collections.abc import Callable
import logging
from typing import TypeVar

from fastapi import HTTPException

from auth.config import AuthDenied, AuthLimited
from auth.mailconfig import MailUnavailable
from storage.pool import StorageUnavailable

T = TypeVar("T")
log = logging.getLogger("aqua.password")


def execute(action: str, work: Callable[[], T]) -> T:
    try:
        return work()
    except AuthLimited as error:
        log.warning("password_event action=deny reason=rate_limited")
        raise HTTPException(
            429,
            "Too many authentication attempts. Try again shortly.",
            headers={"Retry-After": str(error.retry_after)},
        ) from None
    except (StorageUnavailable, MailUnavailable):
        log.warning("password_event action=deny reason=service_unavailable")
        raise HTTPException(503, "Authentication is temporarily unavailable.") from None
    except AuthDenied as error:
        category = str(error)
        if category in {"password_hash_unavailable", "password_policy_unavailable"}:
            log.warning("password_event action=deny reason=service_unavailable")
            raise HTTPException(
                503, "Authentication is temporarily unavailable."
            ) from None
        if category == "password_bootstrap_invalid":
            log.warning("password_event action=deny reason=challenge_invalid")
            raise HTTPException(403, "Start a new authentication attempt.") from None
        if category in {"password_invalid", "email_invalid"}:
            log.warning("password_event action=deny reason=policy_invalid")
            raise HTTPException(
                422,
                "The supplied email or password does not meet the supported policy.",
            ) from None
        if action == "login":
            log.warning("password_event action=deny reason=credentials_invalid")
            raise HTTPException(
                401, "Email or password could not be verified."
            ) from None
        log.warning("password_event action=deny reason=proof_invalid")
        raise HTTPException(
            400, "This authentication proof is invalid or expired."
        ) from None
