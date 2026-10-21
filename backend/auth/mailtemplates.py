"""One canonical mailbox and fixed template per account-mail purpose."""

import re

from auth.config import AuthDenied
from auth.mailconfig import MailUnavailable
from auth.password_policy import normalize_email

TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
NOTICE = "Your AQUA password was changed. If this was not you, contact AQUA support through the website."


def recipient_key(value: str) -> str:
    try:
        normalized = normalize_email(value)
    except AuthDenied:
        raise MailUnavailable("account_mail_recipient_invalid") from None
    if normalized != value:
        raise MailUnavailable("account_mail_recipient_invalid")
    return normalized


def render(
    purpose: str, recipient: str, token: str | None, origin: str
) -> dict[str, str]:
    recipient_key(recipient)
    if purpose == "password_changed":
        if token is not None:
            raise MailUnavailable("account_mail_template_invalid")
        return {"to": recipient, "subject": "AQUA password changed", "text": NOTICE}
    if (
        purpose not in {"verify_email", "reset_password"}
        or not isinstance(token, str)
        or not TOKEN.fullmatch(token)
    ):
        raise MailUnavailable("account_mail_template_invalid")
    action, path = (
        ("Verify your email", "/verify-email")
        if purpose == "verify_email"
        else ("Reset your password", "/reset-password")
    )
    return {
        "to": recipient,
        "subject": "AQUA: " + action,
        "text": action
        + " using this link:\n"
        + origin
        + path
        + "#token="
        + token
        + "\nIf you did not request this, ignore this message.",
    }


def validate(purpose: str, payload: dict[str, str], origin: str) -> None:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"to", "subject", "text"}
        or any(not isinstance(v, str) for v in payload.values())
    ):
        raise MailUnavailable("account_mail_template_invalid")
    found = re.search(r"#token=([A-Za-z0-9_-]{43})(?:\n|$)", payload["text"])
    token = found[1] if found else None
    if render(purpose, payload["to"], token, origin) != payload:
        raise MailUnavailable("account_mail_template_invalid")
