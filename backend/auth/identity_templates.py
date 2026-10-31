"""New fixed templates; legacy and aqua-account-v1 renderers stay unchanged."""

from html import escape
import re
from uuid import UUID

from auth.mailconfig import MailPolicy, MailUnavailable
from auth.mailpurposes import ACCOUNT_TOKENS, NOTICES
from auth.password_policy import normalize_email

PURPOSES = ACCOUNT_TOKENS | (NOTICES - {"password_changed"})


def render(purpose, recipient, token, origin, *, request_id=""):
    MailPolicy(public_origin=origin)
    try:
        if normalize_email(recipient) != recipient:
            raise ValueError
    except (RuntimeError, ValueError, TypeError):
        raise MailUnavailable("account_mail_template_invalid") from None
    if purpose not in PURPOSES:
        raise MailUnavailable("account_mail_template_invalid")
    heading = {
        "email_change_new": "Confirm your new AQUA email",
        "email_change_old": "Confirm your AQUA email change",
        "password_add": "Confirm your AQUA password setup",
        "password_added": "An AQUA password was added",
        "email_changed": "Your AQUA email was changed",
        "google_linked": "A Google sign-in method was added",
        "google_unlinked": "A Google sign-in method was removed",
    }[purpose]
    if purpose in ACCOUNT_TOKENS:
        try:
            canonical = str(UUID(request_id))
        except (TypeError, ValueError, AttributeError):
            raise MailUnavailable("account_mail_template_invalid") from None
        if (
            canonical != request_id
            or not isinstance(token, str)
            or not re.fullmatch(r"[A-Za-z0-9_-]{43}", token)
        ):
            raise MailUnavailable("account_mail_template_invalid")
        url = (
            origin
            + "/account-action/"
            + purpose
            + "#request="
            + request_id
            + "&token="
            + token
        )
        text = (
            heading
            + " using this link:\n"
            + url
            + "\nReturn to the account action you started. Opening this link alone changes nothing. If you did not request it, ignore this message."
        )
    else:
        if token is not None or request_id:
            raise MailUnavailable("account_mail_template_invalid")
        url = origin + "/signin"
        text = (
            heading
            + ". If this was not you, secure your account through the AQUA sign-in page:\n"
            + url
        )
    html = (
        '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>AQUA account</title></head>'
        '<body style="margin:0;background:#eef7f8;color:#17343c;font-family:Arial,sans-serif"><main style="max-width:560px;margin:32px auto;padding:28px;background:white;border:1px solid #c8e3e6;border-radius:12px">'
        '<p style="font-weight:bold;letter-spacing:5px;color:#006b78">AQUA</p><h1 style="font-size:26px">'
        + escape(heading)
        + '</h1><p>Review only the account action you started.</p><p><a href="'
        + escape(url, quote=True)
        + '" style="display:inline-block;padding:14px 22px;background:#006b78;color:white;border-radius:8px">Review account action</a></p><p>If you did not request this, use the AQUA sign-in page to secure your account.</p></main></body></html>'
    )
    return {
        "to": recipient,
        "subject": heading,
        "text": text,
        "html": html,
        "template_version": "aqua-account-v2",
        "purpose": purpose,
        "origin": origin,
        "request_id": request_id,
    }
