"""Explicit single-use worker operation; never starts in the web application."""

import logging
from datetime import datetime, timezone
from typing import Protocol
import uuid

from auth.mailconfig import MailUnavailable
from auth.mailoutbox import open_job
from auth.mailqueue import MailOutbox

log = logging.getLogger("aqua.account_mail")


class MailTransport(Protocol):
    def send(self, job_id: uuid.UUID, payload: dict[str, str]) -> str: ...


class MailWorker:
    def __init__(self, outbox: MailOutbox, transport: MailTransport) -> None:
        self.outbox, self.transport = outbox, transport

    def once(self) -> bool:
        job = self.outbox.claim()
        if job is None:
            return False
        try:
            if job.expires_at <= datetime.now(timezone.utc):
                raise MailUnavailable("account_mail_expired")
            payload = open_job(job, self.outbox.policy)
        except MailUnavailable:
            outcome = "invalid"
        else:
            outcome = self.transport.send(job.id, payload)
        committed = self.outbox.finish(job, outcome)
        # Fixed event categories only; no recipient, job link, response or token.
        reason = outcome if committed else "lease_lost"
        log.info("account_mail_event action=delivery reason=%s", reason)
        return True


def main() -> None:
    """Explicit one-job CLI; configuration never starts a web background thread."""
    import json
    import os
    from auth.mailconfig import load_mail_policy
    from auth.mailtransport import ResendTransport
    from storage.config import load_storage_settings
    from storage.pool import Storage, StorageUnavailable

    storage = None
    try:
        policy = load_mail_policy()
        if (
            not policy.enabled
            or os.environ.get("ACCOUNT_MAIL_WORKER_ENABLED") != "true"
        ):
            raise MailUnavailable("account_mail_worker_disabled")
        storage = Storage(load_storage_settings())
        storage.readiness()
        transport = ResendTransport(os.environ.get("RESEND_API_KEY", ""))
        attempted = MailWorker(MailOutbox(storage, policy), transport).once()
        print(json.dumps({"status": "attempted" if attempted else "idle"}))
    except (MailUnavailable, StorageUnavailable):
        print(
            json.dumps(
                {"status": "unavailable", "detail": "account_mail_worker_failed"}
            )
        )
        raise SystemExit(1) from None
    finally:
        if storage is not None:
            storage.close()


if __name__ == "__main__":
    main()
