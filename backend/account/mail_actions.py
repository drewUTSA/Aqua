"""Mailbox possession plus fresh method proof complete one exact pending action."""

import hashlib
import secrets

from account import action_requests
from account.authority import current_id
from account.google_methods import notice
from account.identity_runtime import admit_action, password_enabled, primary
from account.policy import MAX_REVISION
from account.proof_consumption import check_proof, consume_proof
from account.reset_invalidation import invalidate_resets
from account.revocation import revoke_all
from auth.config import AuthDenied
from auth.mailoutbox import enqueue, ensure_capacity
from auth.password_limits import hash_slot
from auth.password_policy import normalize_email, normalize_password
from auth.sessions import token_digest
from workspace.errors import WorkspaceError


def password_absent(conn, owner):
    if conn.execute(
        "SELECT 1 FROM app.password_credentials WHERE user_id=%s", (owner,)
    ).fetchone():
        raise WorkspaceError("identity_conflict", 409)


def consume_mail(conn, session, pending, purpose, recipient, token):
    row = conn.execute(
        "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() WHERE account_request_id=%s AND user_id=%s AND session_id=(SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s) AND password_auth_epoch=%s AND purpose=%s AND target_email_key=%s AND secret_digest=%s AND consumed_at IS NULL AND expires_at=%s AND expires_at>clock_timestamp() RETURNING id",
        (
            pending.id,
            session.user["id"],
            session.user["id"],
            session.token_digest,
            session.auth_epoch,
            purpose,
            recipient,
            token_digest(token),
            pending.expires_at,
        ),
    ).fetchone()
    if row is None:
        raise WorkspaceError("proof_invalid", 403)
    # New-purpose DB uniqueness admits at most one encrypted job per ticket.
    conn.execute(
        "DELETE FROM app.account_mail WHERE challenge_id=%s AND purpose=%s",
        (row[0], purpose),
    )


def check_mail(conn, session, pending, purpose, recipient, token):
    row = conn.execute(
        "SELECT id FROM app.auth_challenges WHERE account_request_id=%s AND user_id=%s AND session_id=(SELECT id FROM app.sessions WHERE user_id=%s AND token_digest=%s) AND password_auth_epoch=%s AND purpose=%s AND target_email_key=%s AND secret_digest=%s AND consumed_at IS NULL AND expires_at=%s AND expires_at>clock_timestamp()",
        (
            pending.id,
            session.user["id"],
            session.user["id"],
            session.token_digest,
            session.auth_epoch,
            purpose,
            recipient,
            token_digest(token),
            pending.expires_at,
        ),
    ).fetchone()
    if row is None:
        raise WorkspaceError("proof_invalid", 403)


class MailActions:
    def __init__(self, passwords):
        self.passwords = passwords
        self.storage, self.policy = passwords.storage, passwords.auth_policy

    def start(self, session, operation, proof, secret, binding, new_email=None):
        admit_action(self.passwords, session)
        if operation == "password_add":
            password_enabled()
        with self.storage.transaction() as conn:
            ensure_capacity(
                conn,
                self.passwords.mail_policy,
                "password_add" if operation == "password_add" else "email_change_new",
                count=1 if operation == "password_add" else 2,
            )
            sid = current_id(conn, session, self.policy)
            source = primary(conn, session.user["id"])
            target = (
                source[1] if operation == "password_add" else normalize_email(new_email)
            )
            check_proof(
                conn,
                self.policy,
                session,
                operation,
                target,
                proof,
                method="google" if operation == "password_add" else None,
            )
            if operation == "password_add":
                password_absent(conn, session.user["id"])
            elif target == source[1]:
                raise WorkspaceError("identity_conflict", 409)
            else:
                found = conn.execute(
                    "SELECT user_id FROM app.user_emails WHERE email_key=%s", (target,)
                ).fetchone()
                if found and str(found[0]) != session.user["id"]:
                    raise WorkspaceError("identity_conflict", 409)
            proof_identity = conn.execute(
                "SELECT external_identity_id,external_identity_revision FROM app.account_action_proofs WHERE secret_digest=%s",
                (proof,),
            ).fetchone()
            request_id, expiry = action_requests.create(
                conn,
                session,
                sid,
                operation,
                target,
                secret,
                binding,
                google_snapshot=proof_identity if proof_identity[0] else None,
            )
            mails = (
                [("password_add", target)]
                if operation == "password_add"
                else [("email_change_new", target), ("email_change_old", source[1])]
            )
            for purpose, recipient in mails:
                token = secrets.token_urlsafe(32)
                ticket = conn.execute(
                    "INSERT INTO app.auth_challenges(user_id,session_id,purpose,secret_digest,target_email_key,password_auth_epoch,account_request_id,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                    (
                        session.user["id"],
                        sid,
                        purpose,
                        token_digest(token),
                        recipient,
                        session.auth_epoch,
                        request_id,
                        expiry,
                    ),
                ).fetchone()[0]
                enqueue(
                    conn,
                    recipient=recipient,
                    purpose=purpose,
                    token=token,
                    expires_at=expiry,
                    policy=self.passwords.mail_policy,
                    challenge_id=ticket,
                )
        return {
            "schemaVersion": 1,
            "request_id": request_id,
            "expires_at": expiry.isoformat(),
            "confirmation_required": (
                "primary_email" if operation == "password_add" else "old_and_new_email"
            ),
        }

    def add_password(self, session, body, binding):
        admit_action(self.passwords, session)
        password_enabled()
        secret = token_digest(body.request_token)
        proof = token_digest(body.proof_token)
        with self.storage.transaction() as conn:
            current_id(conn, session, self.policy)
            pending = action_requests.load(
                conn,
                session,
                "password_add",
                secret,
                binding,
                request_id=body.request_id,
            )
            check_proof(
                conn,
                self.policy,
                session,
                "password_add",
                pending.source_email,
                proof,
                method="google",
            )
            password_absent(conn, session.user["id"])
            check_mail(
                conn,
                session,
                pending,
                "password_add",
                pending.source_email,
                body.email_token,
            )
        try:
            normalized = normalize_password(body.new_password)
        except AuthDenied:
            raise WorkspaceError("invalid_request", 422) from None
        with hash_slot(self.storage, self.passwords.policy):
            encoded = self.passwords.hasher.hash(normalized)
        with self.storage.transaction() as conn:
            ensure_capacity(conn, self.passwords.mail_policy, "password_added")
            current_id(conn, session, self.policy)
            pending = action_requests.load(
                conn,
                session,
                "password_add",
                secret,
                binding,
                request_id=body.request_id,
            )
            consume_proof(
                conn,
                self.policy,
                session,
                "password_add",
                pending.source_email,
                proof,
                method="google",
            )
            password_absent(conn, session.user["id"])
            consume_mail(
                conn,
                session,
                pending,
                "password_add",
                pending.source_email,
                body.email_token,
            )
            conn.execute(
                "INSERT INTO app.password_credentials(user_id,encoded_hash,policy_version) VALUES(%s,%s,%s)",
                (session.user["id"], encoded, self.passwords.policy.version),
            )
            action_requests.consume(conn, pending)
            revoke_all(conn, session.user["id"], session.auth_epoch)
            notice(conn, self.passwords, pending.source_email, "password_added")
        return {
            "schemaVersion": 1,
            "password_added": True,
            "current_session_revoked": True,
        }

    def change_email(self, session, body, binding):
        admit_action(self.passwords, session)
        secret, proof = token_digest(body.request_token), token_digest(body.proof_token)
        with self.storage.transaction() as conn:
            row = conn.execute(
                "SELECT target_email_key FROM app.account_security_requests WHERE id=%s AND user_id=%s AND operation='email_change' AND secret_digest=%s AND binding_digest=%s AND consumed_at IS NULL AND expires_at>clock_timestamp()",
                (body.request_id, session.user["id"], secret, binding),
            ).fetchone()
            if row is None:
                raise WorkspaceError("proof_invalid", 403)
            target = row[0]
        with self.storage.transaction() as conn:
            ensure_capacity(conn, self.passwords.mail_policy, "email_changed", count=2)
            lock = int.from_bytes(
                hashlib.sha256(target.encode()).digest()[:8], "big", signed=True
            )
            conn.execute("SELECT pg_advisory_xact_lock(%s)", (lock,))
            current_id(conn, session, self.policy)
            pending = action_requests.load(
                conn,
                session,
                "email_change",
                secret,
                binding,
                request_id=body.request_id,
            )
            if pending.target_email != target or pending.source_email == target:
                raise WorkspaceError("proof_invalid", 403)
            consume_proof(conn, self.policy, session, "email_change", target, proof)
            consume_mail(
                conn, session, pending, "email_change_new", target, body.email_token
            )
            consume_mail(
                conn,
                session,
                pending,
                "email_change_old",
                pending.source_email,
                body.old_email_token,
            )
            state = conn.execute(
                "SELECT profile_revision,email_revision FROM app.users WHERE id=%s",
                (session.user["id"],),
            ).fetchone()
            if max(state) >= MAX_REVISION:
                raise WorkspaceError("security_unavailable", 503)
            emails = conn.execute(
                "SELECT id FROM app.user_emails WHERE user_id=%s LIMIT 21",
                (session.user["id"],),
            ).fetchall()
            existing = conn.execute(
                "SELECT id,user_id FROM app.user_emails WHERE email_key=%s", (target,)
            ).fetchone()
            if existing and str(existing[1]) != session.user["id"]:
                raise WorkspaceError("identity_conflict", 409)
            if existing is None and len(emails) >= 20 or len(emails) > 20:
                raise WorkspaceError("security_unavailable", 503)
            invalidate_resets(
                conn, session.user["id"], session.auth_epoch, pending.source_email
            )
            conn.execute(
                "UPDATE app.user_emails SET is_primary=false WHERE user_id=%s AND is_primary",
                (session.user["id"],),
            )
            if existing is None:
                if (
                    conn.execute(
                        "INSERT INTO app.user_emails(user_id,address,email_key,verified_at,verification_method,is_primary) VALUES(%s,%s,%s,clock_timestamp(),'email',true) ON CONFLICT(email_key) DO NOTHING RETURNING id",
                        (session.user["id"], target, target),
                    ).fetchone()
                    is None
                ):
                    raise WorkspaceError("identity_conflict", 409)
            else:
                conn.execute(
                    "UPDATE app.user_emails SET is_primary=true,verified_at=clock_timestamp(),verification_method='email' WHERE id=%s AND user_id=%s",
                    (existing[0], session.user["id"]),
                )
            conn.execute(
                "UPDATE app.users SET email_revision=email_revision+1,profile_revision=profile_revision+1,updated_at=clock_timestamp() WHERE id=%s",
                (session.user["id"],),
            )
            action_requests.consume(conn, pending)
            revoke_all(conn, session.user["id"], session.auth_epoch)
            notice(conn, self.passwords, pending.source_email, "email_changed")
            notice(conn, self.passwords, target, "email_changed")
        return {
            "schemaVersion": 1,
            "email_changed": True,
            "current_session_revoked": True,
        }
