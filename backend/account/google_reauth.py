"""One-use Google action proof with exact active identity revision snapshots."""

from account.authority import current_id
from account.google_verification import fresh_identity
from account.identity_runtime import admit_action
from account.proofs import claim_challenge, create_challenge
from auth.accounts import provider_observation
from auth.sessions import bound_value, new_token, token_digest
from workspace.errors import WorkspaceError


class GoogleRecentAuth:
    def __init__(self, passwords, settings):
        self.passwords, self.settings = passwords, settings
        self.storage, self.policy = passwords.storage, passwords.auth_policy

    def start(self, session, operation, target, identity, secret, binding):
        if not self.settings.google_client_id:
            admit_action(self.passwords, session)
            raise WorkspaceError("method_unavailable", 403)
        challenge = create_challenge(
            self.storage,
            self.policy,
            session,
            operation,
            target,
            token_digest(secret),
            token_digest(binding),
            google_identity=identity,
        )
        with self.storage.transaction() as conn:
            current_id(conn, session, self.policy)
            expiry = conn.execute(
                "SELECT expires_at FROM app.auth_challenges WHERE id=%s AND user_id=%s",
                (challenge, session.user["id"]),
            ).fetchone()[0]
        return {
            "schemaVersion": 1,
            "challenge_id": challenge,
            "challenge_token": secret,
            "expires_at": expiry.isoformat(),
            "client_id": self.settings.google_client_id,
            "nonce": bound_value(self.settings, secret, "account-google-nonce"),
        }

    def verify(
        self, session, operation, target, challenge, secret, binding, credential
    ):
        claimed = claim_challenge(
            self.storage,
            self.policy,
            session,
            challenge,
            operation,
            target,
            token_digest(secret),
            token_digest(binding),
            google=True,
        )
        # claim/admission committed; network and token verification own no lease.
        identity = fresh_identity(
            credential,
            self.settings,
            bound_value(self.settings, secret, "account-google-nonce"),
            claimed.created_at,
        )
        token = new_token()
        with self.storage.transaction() as conn:
            sid = current_id(conn, session, self.policy)
            found = conn.execute(
                "SELECT e.id FROM app.external_identities e JOIN app.auth_challenges c ON c.account_google_identity_id=e.id WHERE c.id=%s AND c.user_id=%s AND c.session_id=%s AND c.account_auth_epoch=%s AND c.consumed_at IS NOT NULL AND c.expires_at>clock_timestamp() AND e.user_id=c.user_id AND e.is_active AND e.revision=c.account_google_identity_revision AND e.revision=%s AND e.issuer='https://accounts.google.com' AND e.subject=%s FOR UPDATE OF c",
                (
                    claimed.id,
                    session.user["id"],
                    sid,
                    session.auth_epoch,
                    claimed.google_identity_revision,
                    identity["sub"],
                ),
            ).fetchone()
            if found is None or str(found[0]) != claimed.google_identity_id:
                raise WorkspaceError("proof_invalid", 403)
            # Only a fully verified, current revision may publish observations.
            # The user lock serializes method mutations and analytical delivery;
            # the existing grant policy then denies contradicted email evidence.
            # This does not change the app mailbox/profile or seed any grant.
            email, authoritative = provider_observation(identity)
            conn.execute(
                "UPDATE app.external_identities SET observed_email_key=%s,email_authoritative=%s WHERE id=%s AND user_id=%s AND is_active AND revision=%s",
                (
                    email,
                    authoritative,
                    claimed.google_identity_id,
                    session.user["id"],
                    claimed.google_identity_revision,
                ),
            )
            expiry = conn.execute(
                "INSERT INTO app.account_action_proofs(user_id,session_id,challenge_id,secret_digest,auth_epoch,operation,target_digest,method,external_identity_id,external_identity_revision,created_at,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,'google',%s,%s,statement_timestamp(),LEAST(statement_timestamp()+interval '300 seconds',%s)) RETURNING expires_at",
                (
                    session.user["id"],
                    sid,
                    claimed.id,
                    token_digest(token),
                    session.auth_epoch,
                    operation,
                    claimed.target_digest,
                    claimed.google_identity_id,
                    claimed.google_identity_revision,
                    claimed.expires_at,
                ),
            ).fetchone()[0]
        return {
            "schemaVersion": 1,
            "proof_token": token,
            "expires_at": expiry.isoformat(),
        }
