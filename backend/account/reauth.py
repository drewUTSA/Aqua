"""Verify only the current account's password, detached from database leases."""

from account.authority import current_id
from account.credentials import PasswordSnapshot, password_snapshot
from account.policy import PROOF_SECONDS
from account.proofs import ClaimedChallenge, claim_challenge, create_challenge
from auth.config import AuthDenied
from auth.password_limits import hash_slot
from auth.password_policy import normalize_password
from auth.passwords import PasswordStore
from auth.security import UserSession
from auth.sessions import new_token, token_digest
from workspace.errors import WorkspaceError


class RecentAuth:
    def __init__(self, passwords: PasswordStore) -> None:
        self.passwords = passwords
        self.storage = passwords.storage
        self.policy = passwords.auth_policy

    def start(
        self,
        session: UserSession,
        operation: str,
        target: object,
        secret: bytes,
        binding: bytes,
    ) -> dict:
        challenge = create_challenge(
            self.storage,
            self.policy,
            session,
            operation,
            target,
            secret,
            binding,
            require_password=True,
        )
        with self.storage.transaction() as conn:
            sid = current_id(conn, session, self.policy)
            expires = conn.execute(
                "SELECT expires_at FROM app.auth_challenges WHERE id=%s AND user_id=%s "
                "AND session_id=%s AND account_auth_epoch=%s AND consumed_at IS NULL "
                "AND expires_at>clock_timestamp()",
                (challenge, session.user["id"], sid, session.auth_epoch),
            ).fetchone()
            if expires is None:
                raise WorkspaceError("proof_invalid", 403)
        return {
            "schemaVersion": 1,
            "challenge_id": challenge,
            "expires_at": expires[0].isoformat(),
            "methods": ["password"],
        }

    def password(
        self,
        session: UserSession,
        challenge: str,
        operation: str,
        target: object,
        secret: bytes,
        binding: bytes,
        password: str,
    ) -> dict:
        claimed = claim_challenge(
            self.storage,
            self.policy,
            session,
            challenge,
            operation,
            target,
            secret,
            binding,
        )
        # Claim and durable admission commit even if policy, capacity or hashing
        # rejects this attempt. No expensive verifier can replay that challenge.
        with self.storage.transaction() as conn:
            current_id(conn, session, self.policy)
            before = password_snapshot(conn, session.user["id"])
        try:
            normalized = normalize_password(password, establish=False)
        except AuthDenied:
            raise WorkspaceError("proof_invalid", 403) from None
        with hash_slot(self.storage, self.passwords.policy):
            accepted = self.passwords.hasher.verify(normalized, before.encoded)
        if not accepted:
            raise WorkspaceError("proof_invalid", 403)
        return self._issue_password_proof(session, claimed, before)

    def _issue_password_proof(
        self,
        session: UserSession,
        claimed: ClaimedChallenge,
        before: PasswordSnapshot,
    ) -> dict:
        # This private path is reached only after actual password verification.
        # No HTTP route accepts a verified flag, hash, method ID or timestamp.
        token = new_token()
        with self.storage.transaction() as conn:
            sid = current_id(conn, session, self.policy)
            if password_snapshot(conn, session.user["id"]) != before:
                raise WorkspaceError("proof_invalid", 403)
            row = conn.execute(
                "SELECT expires_at FROM app.auth_challenges WHERE id=%s AND user_id=%s "
                "AND session_id=%s AND account_auth_epoch=%s AND account_operation=%s "
                "AND account_target_digest=%s AND purpose='reauth' AND consumed_at IS NOT NULL "
                "AND expires_at>clock_timestamp() FOR UPDATE",
                (
                    claimed.id,
                    session.user["id"],
                    sid,
                    session.auth_epoch,
                    claimed.operation,
                    claimed.target_digest,
                ),
            ).fetchone()
            if (
                row is None
                or claimed.owner != session.user["id"]
                or claimed.session_id != sid
                or claimed.auth_epoch != session.auth_epoch
            ):
                raise WorkspaceError("proof_invalid", 403)
            expiry = conn.execute(
                "INSERT INTO app.account_action_proofs(user_id,session_id,challenge_id,secret_digest,"
                "auth_epoch,operation,target_digest,method,password_changed_at,created_at,expires_at) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,'password',%s,statement_timestamp(),"
                "LEAST(statement_timestamp()+%s*interval '1 second',%s)) RETURNING expires_at",
                (
                    session.user["id"],
                    sid,
                    claimed.id,
                    token_digest(token),
                    session.auth_epoch,
                    claimed.operation,
                    claimed.target_digest,
                    before.changed_at,
                    PROOF_SECONDS,
                    row[0],
                ),
            ).fetchone()[0]
        return {
            "schemaVersion": 1,
            "proof_token": token,
            "expires_at": expiry.isoformat(),
        }
