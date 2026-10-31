"""Explicit two-method linking and user-locked last-method removal."""

import hashlib
import os

from account import action_requests
from account.authority import current_id
from account.google_verification import fresh_identity
from account.identity_runtime import admit_action, primary
from account.policy import MAX_REVISION
from account.proof_consumption import check_proof, consume_proof
from account.revocation import revoke_all
from auth.accounts import provider_observation
from auth.mailoutbox import enqueue, ensure_capacity
from auth.sessions import bound_value, new_token, token_digest
from workspace.errors import WorkspaceError


def notice(conn, passwords, recipient, purpose):
    expiry = conn.execute("SELECT clock_timestamp()+interval '1 hour'").fetchone()[0]
    enqueue(
        conn,
        recipient=recipient,
        purpose=purpose,
        token=None,
        expires_at=expiry,
        policy=passwords.mail_policy,
    )


def subject_lock(conn, subject):
    # Identical lock domain/order to Google first-login resolution.
    value = int.from_bytes(
        hashlib.sha256(("https://accounts.google.com\0" + subject).encode()).digest()[
            :8
        ],
        "big",
        signed=True,
    )
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (value,))


def revoke_identity_grants(conn, owner, identity_id):
    grants = conn.execute(
        "SELECT dataset_key FROM app.dataset_grants WHERE user_id=%s AND approval_identity_id=%s AND approval_kind IN ('google_subject','google_email') AND revoked_at IS NULL LIMIT 21",
        (owner, identity_id),
    ).fetchall()
    if len(grants) > 20:
        raise WorkspaceError("security_unavailable", 503)
    if grants:
        conn.execute(
            "UPDATE app.dataset_grants SET revoked_at=clock_timestamp() WHERE user_id=%s AND approval_identity_id=%s AND approval_kind IN ('google_subject','google_email') AND revoked_at IS NULL AND dataset_key=ANY(%s)",
            (owner, identity_id, [row[0] for row in grants]),
        )


class GoogleMethods:
    def __init__(self, passwords, settings):
        self.passwords, self.settings = passwords, settings
        self.storage, self.policy = passwords.storage, passwords.auth_policy

    def start(self, session, proof, secret, binding):
        admit_action(self.passwords, session)
        if not self.settings.google_client_id or not self.passwords.mail_policy.enabled:
            raise WorkspaceError("method_unavailable", 403)
        with self.storage.transaction() as conn:
            # Request expiry cleanup cascades to token-mail rows. Take the
            # established mail lock before user/request locks even though this
            # provider challenge does not enqueue a job yet.
            ensure_capacity(conn, self.passwords.mail_policy, "google_linked")
            sid = current_id(conn, session, self.policy)
            check_proof(conn, self.policy, session, "google_link", None, proof)
            request, expiry = action_requests.create(
                conn,
                session,
                sid,
                "google_link",
                None,
                token_digest(secret),
                token_digest(binding),
            )
        return {
            "schemaVersion": 1,
            "challenge_id": request,
            "challenge_token": secret,
            "expires_at": expiry.isoformat(),
            "client_id": self.settings.google_client_id,
            "nonce": bound_value(self.settings, secret, "account-google-link-nonce"),
        }

    def candidate(self, session, request, secret, binding, credential):
        admit_action(self.passwords, session)
        with self.storage.transaction() as conn:
            current_id(conn, session, self.policy)
            pending = action_requests.load(
                conn,
                session,
                "google_link",
                token_digest(secret),
                token_digest(binding),
                request_id=request,
            )
            if pending.claimed_at is not None:
                raise WorkspaceError("proof_invalid", 403)
            conn.execute(
                "UPDATE app.account_security_requests SET claimed_at=clock_timestamp() WHERE id=%s",
                (pending.id,),
            )
        identity = fresh_identity(
            credential,
            self.settings,
            bound_value(self.settings, secret, "account-google-link-nonce"),
            pending.created_at,
        )
        candidate = new_token()
        with self.storage.transaction() as conn:
            current_id(conn, session, self.policy)
            pending = action_requests.load(
                conn,
                session,
                "google_link",
                token_digest(secret),
                token_digest(binding),
                request_id=request,
            )
            if pending.claimed_at is None or pending.verified_at is not None:
                raise WorkspaceError("proof_invalid", 403)
            email, authoritative = provider_observation(identity)
            conn.execute(
                "UPDATE app.account_security_requests SET google_subject=%s,google_email_key=%s,google_email_authoritative=%s,verified_at=clock_timestamp(),secret_digest=%s WHERE id=%s",
                (
                    identity["sub"],
                    email,
                    authoritative,
                    token_digest(candidate),
                    pending.id,
                ),
            )
        return {
            "schemaVersion": 1,
            "candidate_token": candidate,
            "expires_at": pending.expires_at.isoformat(),
            "google": {"email": email},
        }

    def link(self, session, proof, candidate, binding):
        admit_action(self.passwords, session)
        # Read only the exact owned candidate before acquiring mail -> subject
        # -> user, never user -> subject (Google login takes subject -> user).
        with self.storage.transaction() as conn:
            row = conn.execute(
                "SELECT google_subject FROM app.account_security_requests WHERE user_id=%s AND secret_digest=%s AND binding_digest=%s AND operation='google_link' AND verified_at IS NOT NULL AND consumed_at IS NULL AND expires_at>clock_timestamp()",
                (session.user["id"], candidate, binding),
            ).fetchone()
            if row is None:
                raise WorkspaceError("proof_invalid", 403)
            subject = row[0]
        with self.storage.transaction() as conn:
            ensure_capacity(conn, self.passwords.mail_policy, "google_linked")
            subject_lock(conn, subject)
            current_id(conn, session, self.policy)
            pending = action_requests.load(
                conn, session, "google_link", candidate, binding
            )
            if pending.google_subject != subject or pending.verified_at is None:
                raise WorkspaceError("proof_invalid", 403)
            consume_proof(conn, self.policy, session, "google_link", None, proof)
            identity = conn.execute(
                "SELECT id,user_id,is_active,revision FROM app.external_identities WHERE issuer='https://accounts.google.com' AND subject=%s FOR UPDATE",
                (subject,),
            ).fetchone()
            if identity is not None and (
                str(identity[1]) != session.user["id"] or identity[2]
            ):
                raise WorkspaceError("identity_conflict", 409)
            active = conn.execute(
                "SELECT id FROM app.external_identities WHERE user_id=%s AND is_active LIMIT 21",
                (session.user["id"],),
            ).fetchall()
            if (
                len(active) >= 20
                or identity is not None
                and identity[3] >= MAX_REVISION
            ):
                raise WorkspaceError("security_unavailable", 503)
            if identity is None:
                conn.execute(
                    "INSERT INTO app.external_identities(user_id,provider,issuer,subject,observed_email_key,email_authoritative) VALUES(%s,'google','https://accounts.google.com',%s,%s,%s)",
                    (
                        session.user["id"],
                        subject,
                        pending.google_email,
                        pending.google_authoritative,
                    ),
                )
            else:
                revoke_identity_grants(conn, session.user["id"], identity[0])
                conn.execute(
                    "UPDATE app.external_identities SET is_active=true,inactive_at=NULL,revision=revision+1,linked_at=clock_timestamp(),observed_email_key=%s,email_authoritative=%s WHERE id=%s",
                    (pending.google_email, pending.google_authoritative, identity[0]),
                )
            action_requests.consume(conn, pending)
            revoke_all(conn, session.user["id"], session.auth_epoch)
            notice(conn, self.passwords, pending.source_email, "google_linked")
        return {"schemaVersion": 1, "linked": True, "current_session_revoked": True}

    def unlink(self, session, identity_id, proof):
        admit_action(self.passwords, session)
        with self.storage.transaction() as conn:
            ensure_capacity(conn, self.passwords.mail_policy, "google_unlinked")
            current_id(conn, session, self.policy)
            identities = conn.execute(
                "SELECT id,revision FROM app.external_identities WHERE user_id=%s AND is_active LIMIT 21",
                (session.user["id"],),
            ).fetchall()
            if len(identities) > 20:
                raise WorkspaceError("security_unavailable", 503)
            target = conn.execute(
                "SELECT id,revision FROM app.external_identities WHERE user_id=%s AND id=%s AND is_active FOR UPDATE",
                (session.user["id"], identity_id),
            ).fetchone()
            if target is None:
                raise WorkspaceError("not_found", 404)
            password = (
                os.environ.get("PASSWORD_AUTH_ENABLED", "false") == "true"
                and conn.execute(
                    "SELECT 1 FROM app.password_credentials WHERE user_id=%s",
                    (session.user["id"],),
                ).fetchone()
                is not None
            )
            if not password and not (
                self.settings.google_client_id and len(identities) >= 2
            ):
                raise WorkspaceError("last_method", 409)
            if target[1] >= MAX_REVISION:
                raise WorkspaceError("security_unavailable", 503)
            consume_proof(
                conn, self.policy, session, "google_unlink", identity_id, proof
            )
            revoke_identity_grants(conn, session.user["id"], identity_id)
            conn.execute(
                "UPDATE app.external_identities SET is_active=false,inactive_at=clock_timestamp(),revision=revision+1 WHERE user_id=%s AND id=%s",
                (session.user["id"], identity_id),
            )
            recipient = primary(conn, session.user["id"])[1]
            revoke_all(conn, session.user["id"], session.auth_epoch)
            notice(conn, self.passwords, recipient, "google_unlinked")
        return {"schemaVersion": 1, "unlinked": True, "current_session_revoked": True}
