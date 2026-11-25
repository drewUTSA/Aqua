"""Request one verified-mailbox invitation from inside the running Aqua backend."""

from contextlib import nullcontext
from http.client import HTTPConnection
import json
import logging
import os
import sys

from auth.config import load_auth_policy
from auth.mailconfig import load_mail_policy
from auth.password_policy import PasswordPolicy, normalize_email
from auth.password_settings import check_action
from auth.passwords import PasswordStore
from auth.security import ensure_configured
from nl2sql.config import settings_from
from retirement.checkpoint import ProtectedFile
from retirement.mail_physical import gate
from retirement.settings import DIRECTORY, load as retirement_settings
from storage.config import load_storage_settings
from storage.pool import SCHEMA_VERSION, Storage


class Unavailable(Exception):
    """The caller receives one fixed failure response without operational data."""


def recipient(stream):
    raw = stream.read(257)
    if len(raw) > 256:
        raise Unavailable()
    if raw.endswith(b"\n"):
        raw = raw[:-1].removesuffix(b"\r")
    return normalize_email(raw.decode("ascii"))


def require_running_web():
    # Only the actual web process owns the reconciled retirement runtime.
    connection = HTTPConnection("127.0.0.1", 8000, timeout=2)
    try:
        connection.request("GET", "/api/ready")
        reply = connection.getresponse()
        body = reply.read(257)
        if (
            reply.status != 200
            or len(body) > 256
            or json.loads(body)
            != {
                "status": "ready",
                "application_storage": "ready",
                "schema_version": SCHEMA_VERSION,
            }
        ):
            raise Unavailable()
    finally:
        connection.close()


def current_checkpoint(authority):
    if authority is None:
        return None
    checkpoint = ProtectedFile(
        DIRECTORY / "checkpoints.bin",
        owner_uid=1000,
        public_key=authority.public_key,
        installation=authority.installation,
        key_id=authority.identity.key_id,
        commitment=authority.identity.commitment,
    )
    # A new process has no previously verified inode. Scan the signed chain
    # before taking the physical mail lock or holding a database transaction.
    checkpoint.head(full=True)
    return checkpoint


def require_current(conn, checkpoint):
    # Hold the shared control-row lock through the existing password transactions.
    # Recovery and deletion admission take this row FOR UPDATE.
    row = conn.execute(
        "SELECT recovery_required,authority_installed,permanent_intents,"
        "EXISTS(SELECT 1 FROM pg_database WHERE datname='aqua_retirement') "
        "FROM app.retirement_control WHERE singleton FOR SHARE"
    ).fetchone()
    installed = checkpoint is not None
    if row is None or row[0] or row[1] != installed or row[3] != installed:
        raise Unavailable()
    count, pending, latest = conn.execute(
        "SELECT count(*),count(*) FILTER (WHERE authority_sequence IS NULL),"
        "max(authority_sequence) FROM app.retirement_intents"
    ).fetchone()
    if pending or count != row[2] or latest != (count or None):
        raise Unavailable()
    if not installed:
        if count:
            raise Unavailable()
        return
    head = checkpoint.head()
    if head.sequence != count or (
        count
        and conn.execute(
            "SELECT installation_id::text,event_digest FROM app.retirement_intents "
            "WHERE authority_sequence=%s",
            (count,),
        ).fetchone()
        != (head.installation, head.event_digest)
    ):
        raise Unavailable()


def request_invitation(email):
    check_action("verification")
    settings = settings_from(os.environ)
    ensure_configured(settings)
    mail = load_mail_policy()
    if not mail.enabled or mail.public_origin != settings.app_origin:
        raise Unavailable()
    password = PasswordPolicy(
        verification_seconds=int(
            os.environ.get("PASSWORD_VERIFICATION_SECONDS", "86400")
        ),
        reset_seconds=int(os.environ.get("PASSWORD_RESET_SECONDS", "1800")),
    )
    auth = load_auth_policy(settings)
    checkpoint = current_checkpoint(retirement_settings())
    storage = Storage(load_storage_settings())
    try:
        # A second bounded lease lets PasswordStore retain its original independent
        # admission/commit semantics, including per-address and global budgets.
        if not storage.settings.enabled or storage.settings.max_connections < 2:
            raise Unavailable()
        with gate() if checkpoint is not None else nullcontext(True) as acquired:
            if not acquired:
                raise Unavailable()
            with storage.transaction() as conn:
                require_current(conn, checkpoint)
                require_running_web()
                PasswordStore(storage, auth, password, mail).request_email(
                    email, "verify_email", "operator-mailbox-invitation"
                )
    finally:
        storage.close()


def main():
    # Third-party driver diagnostics may contain hostnames or configuration. This
    # dedicated one-shot process exposes only the two documented messages.
    logging.disable(logging.CRITICAL)
    try:
        if len(sys.argv) != 1 or sys.stdin.isatty():
            raise Unavailable()
        request_invitation(recipient(sys.stdin.buffer))
    except Exception:
        print("Invitation unavailable.", file=sys.stderr)
        return 1
    print("Invitation request accepted.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
