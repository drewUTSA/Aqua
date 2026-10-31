"""Sensitive actions commit proof, mutation and required notice together."""

from account.authority import current_id
from account.credentials import password_snapshot
from account.proof_consumption import check_proof, consume_proof
from account.revocation import revoke_all
from account.reset_invalidation import invalidate_resets
from auth.admission import admit
from auth.config import AuthDenied
from auth.mailconfig import MailUnavailable
from auth.mailoutbox import enqueue, ensure_capacity
from auth.password_limits import hash_slot
from auth.password_policy import normalize_password
from auth.passwords import PasswordStore
from auth.security import UserSession
from workspace.errors import WorkspaceError


class SecurityActions:
    def __init__(self, passwords: PasswordStore) -> None:
        self.passwords = passwords
        self.storage = passwords.storage
        self.policy = passwords.auth_policy

    def _admit(self, session: UserSession) -> None:
        with self.storage.transaction() as conn:
            current_id(conn, session, self.policy)
            admit(conn, self.policy, "action", account_id=session.user["id"])

    def password(self, session: UserSession, secret: bytes, value: str) -> dict:
        self._admit(session)
        with self.storage.transaction() as conn:
            check_proof(
                conn,
                self.policy,
                session,
                "password_change",
                None,
                secret,
                method="password",
            )
            before = password_snapshot(conn, session.user["id"])
        if not self.passwords.mail_policy.enabled:
            raise MailUnavailable("account_mail_disabled")
        try:
            normalized = normalize_password(value)
        except AuthDenied:
            raise WorkspaceError("invalid_request", 422) from None
        with hash_slot(self.storage, self.passwords.policy):
            encoded = self.passwords.hasher.hash(normalized)
        with self.storage.transaction() as conn:
            # Existing reset holds mail admission -> user. Preserve that order;
            # user -> mail here would deadlock a concurrent reset/change.
            ensure_capacity(conn, self.passwords.mail_policy, "password_changed")
            consume_proof(
                conn,
                self.policy,
                session,
                "password_change",
                None,
                secret,
                method="password",
            )
            if password_snapshot(conn, session.user["id"]) != before:
                raise WorkspaceError("proof_invalid", 403)
            invalidate_resets(
                conn, session.user["id"], session.auth_epoch, before.email
            )
            conn.execute(
                "UPDATE app.password_credentials SET encoded_hash=%s,policy_version=%s,changed_at=clock_timestamp() WHERE user_id=%s",
                (encoded, self.passwords.policy.version, session.user["id"]),
            )
            revoke_all(conn, session.user["id"], session.auth_epoch)
            expiry = conn.execute(
                "SELECT clock_timestamp()+interval '1 hour'"
            ).fetchone()[0]
            enqueue(
                conn,
                recipient=before.email,
                purpose="password_changed",
                token=None,
                expires_at=expiry,
                policy=self.passwords.mail_policy,
            )
        return {
            "schemaVersion": 1,
            "password_changed": True,
            "current_session_revoked": True,
        }

    def session(self, session: UserSession, target: str | None, secret: bytes) -> dict:
        self._admit(session)
        operation = "sessions_revoke_all" if target is None else "session_revoke"
        with self.storage.transaction() as conn:
            sid = current_id(conn, session, self.policy)
            password_snapshot(conn, session.user["id"])
            consume_proof(
                conn, self.policy, session, operation, target, secret, method="password"
            )
            if target is None:
                revoke_all(conn, session.user["id"], session.auth_epoch)
            else:
                conn.execute(
                    "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE id=%s AND user_id=%s AND auth_epoch=%s",
                    (target, session.user["id"], session.auth_epoch),
                )
        return {
            "schemaVersion": 1,
            "revoked": True,
            "current_session_revoked": target is None or target == sid,
        }
