"""One canonical mailbox and fixed template per account-mail purpose."""

from html import escape
import re

from auth.config import AuthDenied
from auth.mailconfig import MailPolicy, MailUnavailable
from auth.password_policy import normalize_email
from auth.identity_templates import (
    PURPOSES as IDENTITY_PURPOSES,
    render as identity_render,
)

TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")
NOTICE = "Your AQUA password was changed. If this was not you, contact AQUA support through the website."
TEMPLATE_VERSION = "aqua-account-v1"
PURPOSES = {"verify_email", "reset_password", "password_changed"}
LEGACY_FIELDS = frozenset({"to", "subject", "text"})
VERSIONED_FIELDS = LEGACY_FIELDS | {"template_version", "purpose", "origin", "html"}


def recipient_key(value: str) -> str:
    try:
        normalized = normalize_email(value)
    except AuthDenied:
        raise MailUnavailable("account_mail_recipient_invalid") from None
    if normalized != value:
        raise MailUnavailable("account_mail_recipient_invalid")
    return normalized


def _legacy_render(
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


def _html(purpose: str, token: str | None, origin: str) -> str:
    """Fixed, self-contained email: no active content or remotely loaded assets."""
    heading, label, description = {
        "verify_email": (
            "Welcome to AQUA.",
            "VERIFY YOUR EMAIL",
            "Confirm your email address to finish creating your AQUA account.",
        ),
        "reset_password": (
            "A fresh start, securely.",
            "RESET YOUR PASSWORD",
            "Choose a new password for your AQUA account using the secure link below.",
        ),
        "password_changed": (
            "Your password was changed.",
            "ACCOUNT SECURITY",
            "Your AQUA password has been updated. If this was not you, reset your password now to secure your account.",
        ),
    }[purpose]
    if purpose == "password_changed":
        link = escape(origin + "/forgot-password", quote=True)
        action = (
            '<p style="margin:28px 0"><a href="'
            + link
            + '" style="display:inline-block;padding:14px 22px;border-radius:8px;'
            'background:#006b78;color:#ffffff;text-decoration:none;font-weight:700">'
            "Secure your account</a></p>"
        )
        guidance = (
            "Keep your password private. AQUA will never ask you to send it by email."
        )
    else:
        path, caption = (
            ("/verify-email", "Verify email address")
            if purpose == "verify_email"
            else ("/reset-password", "Reset password")
        )
        link = escape(origin + path + "#token=" + str(token), quote=True)
        action = (
            '<p style="margin:28px 0"><a href="'
            + link
            + '" style="display:inline-block;padding:14px 22px;border-radius:8px;'
            'background:#006b78;color:#ffffff;text-decoration:none;font-weight:700">'
            + caption
            + "</a></p>"
        )
        guidance = "This link expires and can be used only once. If you did not request it, you can safely ignore this email."
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        "<title>AQUA account</title></head>"
        '<body style="margin:0;background:#eef7f8;color:#17343c;font-family:Arial,sans-serif">'
        '<table role="presentation" style="width:100%;border-collapse:collapse"><tr>'
        '<td align="center" style="padding:32px 16px">'
        '<table role="presentation" style="width:100%;max-width:560px;border-collapse:collapse;'
        'background:#ffffff;border:1px solid #c8e3e6;border-radius:12px"><tr>'
        '<td style="padding:28px 32px;border-bottom:1px solid #d9ebed">'
        '<div style="color:#006b78;font-size:30px;font-weight:700;letter-spacing:5px">AQUA</div>'
        '<div style="margin-top:8px;color:#48646b;font-size:11px;font-weight:700;letter-spacing:2px">'
        + label
        + '</div></td></tr><tr><td style="padding:32px">'
        '<h1 style="margin:0 0 18px;font-size:26px;line-height:1.25">'
        + heading
        + '</h1><p style="margin:0;font-size:16px;line-height:1.65">'
        + description
        + "</p>"
        + action
        + '<p style="margin:24px 0 0;color:#48646b;font-size:14px;line-height:1.65">'
        + guidance
        + '</p></td></tr><tr><td style="padding:20px 32px;border-top:1px solid #d9ebed;'
        'color:#48646b;font-size:12px;line-height:1.6">'
        "AQUA &middot; Account notifications<br>Sent automatically. Please do not reply."
        "</td></tr></table></td></tr></table></body></html>"
    )


def render(
    purpose: str,
    recipient: str,
    token: str | None,
    origin: str,
    *,
    request_id: str = "",
) -> dict[str, str]:
    """Persist the complete versioned body so retries do not re-render new content."""
    if purpose in IDENTITY_PURPOSES:
        return identity_render(purpose, recipient, token, origin, request_id=request_id)
    if request_id:
        raise MailUnavailable("account_mail_template_invalid")
    MailPolicy(public_origin=origin)
    payload = _legacy_render(purpose, recipient, token, origin)
    if purpose == "password_changed":
        payload["text"] = (
            "Your AQUA password was changed. If this was not you, reset your password now:\n"
            + origin
            + "/forgot-password\nKeep your password private. AQUA will never ask you to send it by email."
        )
    return {
        **payload,
        "template_version": TEMPLATE_VERSION,
        "purpose": purpose,
        "origin": origin,
        "html": _html(purpose, token, origin),
    }


def validate(purpose: str, payload: dict[str, str], origin: str) -> None:
    if purpose in IDENTITY_PURPOSES:
        if (
            not isinstance(payload, dict)
            or frozenset(payload) != VERSIONED_FIELDS | {"request_id"}
            or any(not isinstance(value, str) for value in payload.values())
        ):
            raise MailUnavailable("account_mail_template_invalid")
        found = re.search(r"&token=([A-Za-z0-9_-]{43})(?:\n|$)", payload["text"])
        token = found[1] if found else None
        if (
            identity_render(
                purpose, payload["to"], token, origin, request_id=payload["request_id"]
            )
            != payload
        ):
            raise MailUnavailable("account_mail_template_invalid")
        return
    if (
        not isinstance(payload, dict)
        or frozenset(payload) not in {LEGACY_FIELDS, VERSIONED_FIELDS}
        or any(not isinstance(v, str) for v in payload.values())
    ):
        raise MailUnavailable("account_mail_template_invalid")
    found = re.search(r"#token=([A-Za-z0-9_-]{43})(?:\n|$)", payload["text"])
    token = found[1] if found else None
    # Original three-field envelopes remain byte-for-byte plain text on retries.
    # A later template version must retain its renderer until those jobs expire.
    renderer = _legacy_render if frozenset(payload) == LEGACY_FIELDS else render
    if renderer(purpose, payload.get("to", ""), token, origin) != payload:
        raise MailUnavailable("account_mail_template_invalid")
