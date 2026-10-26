"""Fixed-origin Resend adapter; retries are owned by the durable outbox, not HTTP."""

from dataclasses import dataclass, field
import re
import time
import uuid

import httpx

from auth.mailconfig import MailUnavailable
from auth.mailtemplates import validate

SENDER = "AQUA <no-reply@account.aqua-ai.us>"


@dataclass(frozen=True)
class ResendTransport:
    key: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not re.fullmatch(
            r"re_[A-Za-z0-9_-]{8,253}", self.key
        ):
            raise MailUnavailable("account_mail_transport_configuration_invalid")

    def send(self, job_id: uuid.UUID, payload: dict[str, str]) -> str:
        # No proxy/env trust, redirect following, SDK retry, or configurable URL.
        # The worker opens the exact canonical encrypted envelope first. Retain
        # legacy bodies unchanged; only versioned envelopes carry branded HTML.
        if (
            not isinstance(payload, dict)
            or not {"to", "subject", "text"} <= set(payload)
            or any(not isinstance(value, str) for value in payload.values())
        ):
            return "invalid"
        body = {
            "from": SENDER,
            "to": [payload["to"]],
            "subject": payload["subject"],
            "text": payload["text"],
        }
        if set(payload) != {"to", "subject", "text"}:
            try:
                validate(payload.get("purpose", ""), payload, payload.get("origin", ""))
            except MailUnavailable:
                return "invalid"
            body["html"] = payload["html"]
            body["tags"] = [
                {"name": "app", "value": "aqua"},
                {"name": "purpose", "value": payload["purpose"]},
                {"name": "template", "value": payload["template_version"]},
            ]
        try:
            with httpx.Client(
                trust_env=False,
                follow_redirects=False,
                timeout=httpx.Timeout(5, connect=3, write=5, pool=1),
                limits=httpx.Limits(max_connections=1, max_keepalive_connections=0),
            ) as client:
                started = time.monotonic()
                with client.stream(
                    "POST",
                    "https://api.resend.com/emails",
                    json=body,
                    headers={
                        "Authorization": "Bearer " + self.key,
                        "Idempotency-Key": "aqua-account-mail/" + str(job_id),
                    },
                ) as response:
                    count = 0
                    for chunk in response.iter_raw():
                        count += len(chunk)
                        if count > 16384 or time.monotonic() - started > 10:
                            return "retry"
                    if 200 <= response.status_code < 300:
                        return "accepted"
                    return (
                        "retry"
                        if response.status_code == 429 or response.status_code >= 500
                        else "permanent"
                    )
        except httpx.HTTPError:
            # Acceptance may be unknown: same stable idempotency key on retry,
            # max three attempts and never beyond 23h (provider retains 24h).
            return "retry"
