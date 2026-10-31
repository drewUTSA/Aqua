"""Google actions must remain independent of the password-login feature flag."""

import os

from fastapi import Depends, Request

from account.authority import current_id
from auth.admission import admit
from auth.mailconfig import MailPolicy, MailUnavailable, load_mail_policy
from auth.password_policy import PasswordPolicy, normalize_email
from auth.passwords import PasswordStore
from auth.security import get_store
from auth.store import IdentityStore
from workspace.errors import WorkspaceError


def get_identity_passwords(
    request: Request, store: IdentityStore = Depends(get_store)
) -> PasswordStore:
    try:
        mail = load_mail_policy()
        if mail.public_origin != request.app.state.settings.app_origin:
            raise MailUnavailable("account_mail_origin_mismatch")
    except MailUnavailable:
        mail = MailPolicy()
    return PasswordStore(store.storage, store.policy, PasswordPolicy(), mail)


def admit_action(passwords, session):
    with passwords.storage.transaction() as conn:
        current_id(conn, session, passwords.auth_policy)
        admit(conn, passwords.auth_policy, "action", account_id=session.user["id"])


def password_enabled():
    if os.environ.get("PASSWORD_AUTH_ENABLED", "false") != "true":
        raise WorkspaceError("method_unavailable", 403)


def primary(conn, owner):
    row = conn.execute(
        "SELECT e.id,e.email_key,u.email_revision FROM app.users u JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary AND e.verified_at IS NOT NULL WHERE u.id=%s",
        (owner,),
    ).fetchone()
    if row is None:
        raise WorkspaceError("session_invalid", 401)
    return row


def action_target(session, body):
    if body.operation == "password_add":
        # The primitive resolves this only after committing action admission.
        def mailbox(conn):
            password_enabled()
            if conn.execute(
                "SELECT 1 FROM app.password_credentials WHERE user_id=%s",
                (session.user["id"],),
            ).fetchone():
                raise WorkspaceError("method_unavailable", 403)
            value = primary(conn, session.user["id"])[1]
            try:
                if normalize_email(value) != value:
                    raise ValueError
            except (RuntimeError, ValueError):
                raise WorkspaceError("method_unavailable", 403) from None
            return value

        return mailbox
    if body.operation == "email_change":
        return body.new_email
    return (
        body.target_identity_id
        if body.operation == "google_unlink"
        else body.target_session_id
    )
