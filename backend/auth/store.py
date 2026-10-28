"""Digest-only sessions, durable challenges and bounded authentication work."""

from dataclasses import dataclass
from typing import Any

from auth.accounts import (
    grant_state,
    preserve_approved_grant,
    resolve_account,
    validate_identity,
)
from auth.admission import admit, cleanup
from auth.config import AuthDenied, AuthLimited, AuthPolicy, dataset_key
from nl2sql.config import Settings
from storage.pool import Storage

ACTIVE_SESSIONS_SQL = (
    "SELECT id FROM app.sessions WHERE user_id=%s AND auth_epoch=%s "
    "AND revoked_at IS NULL AND idle_expires_at>%s LIMIT %s"
)


@dataclass(frozen=True)
class StoredSession:
    id: str
    user: dict[str, Any]
    csrf_digest: bytes
    auth_epoch: int
    dataset_key: str
    grant_version: int
    can_query: bool


def _digest(value: bytes) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise AuthDenied("authentication_token_invalid")


class IdentityStore:
    def __init__(self, storage: Storage, policy: AuthPolicy = AuthPolicy()) -> None:
        self.storage, self.policy = storage, policy

    def issue_challenge(
        self, secret_digest: bytes, binding_digest: bytes, peer_key: str
    ) -> None:
        _digest(secret_digest)
        _digest(binding_digest)
        with self.storage.transaction() as conn:
            admit(conn, self.policy, "challenge", peer_key)
            cleanup(conn, self.policy)
            conn.execute(
                "INSERT INTO app.auth_challenges(purpose,secret_digest,binding_digest,expires_at) "
                "VALUES ('google_login',%s,%s,now()+%s*interval '1 second')",
                (secret_digest, binding_digest, self.policy.challenge_seconds),
            )

    def consume_challenge(self, secret_digest: bytes, binding_digest: bytes) -> None:
        """Compare-and-consume commits before a caller invokes the provider."""
        _digest(secret_digest)
        _digest(binding_digest)
        with self.storage.transaction() as conn:
            consumed = conn.execute(
                "UPDATE app.auth_challenges SET consumed_at=clock_timestamp() "
                "WHERE purpose='google_login' AND secret_digest=%s AND binding_digest=%s "
                "AND consumed_at IS NULL AND expires_at>clock_timestamp() RETURNING id",
                (secret_digest, binding_digest),
            ).fetchone()
            if consumed is None:
                raise AuthDenied("login_challenge_invalid")

    def reserve_login(self, peer_key: str) -> None:
        """Commit callback admission before any external verifier is invoked."""
        with self.storage.transaction() as conn:
            admit(conn, self.policy, "login", peer_key)

    def login(
        self,
        identity: dict[str, Any],
        token_digest: bytes,
        csrf_digest: bytes,
        peer_key: str,
        settings: Settings,
    ) -> StoredSession:
        _digest(token_digest)
        _digest(csrf_digest)
        validate_identity(identity)
        expected = dataset_key(settings) if settings.database_url else ""
        if (
            self.policy.dataset_key != expected
            or not 300 <= settings.session_max_age_seconds <= 86400
        ):
            raise AuthDenied("authentication_policy_mismatch")
        # The route reserves peer/global work before contacting Google. This
        # post-verification stage adds a canonical-account budget that persists
        # across cookies, browser headers, worker restarts and session-cap errors.
        with self.storage.transaction() as conn:
            owner = resolve_account(conn, identity)
        with self.storage.transaction() as conn:
            admit(conn, self.policy, "account", account_id=owner)
        with self.storage.transaction() as conn:
            state = conn.execute(
                "SELECT status,auth_epoch FROM app.users WHERE id=%s FOR UPDATE",
                (owner,),
            ).fetchone()
            if state is None or state[0] != "active":
                raise AuthDenied("account_inactive")
            # Resolution/admission committed before this transaction. Recheck
            # the exact identity under the user lock so a later unlink cannot
            # race an in-flight Google sign-in into creating a usable session.
            linked = conn.execute(
                "SELECT id FROM app.external_identities WHERE user_id=%s "
                "AND issuer='https://accounts.google.com' AND subject=%s AND is_active",
                (owner, identity["sub"]),
            ).fetchone()
            if linked is None:
                raise AuthDenied("identity_inactive")
            cleanup(conn, self.policy)
            instant = conn.execute("SELECT clock_timestamp()").fetchone()[0]
            active = conn.execute(
                # idle<=absolute is a DB constraint. The stable value enables
                # an index range seek; no eviction ordering is needed here.
                ACTIVE_SESSIONS_SQL,
                (owner, state[1], instant, self.policy.max_sessions),
            ).fetchall()
            if len(active) >= self.policy.max_sessions:
                raise AuthLimited(self.policy.window_seconds)
            preserve_approved_grant(conn, owner, self.policy, identity["sub"])
            conn.execute(
                "INSERT INTO app.sessions(user_id,token_digest,csrf_digest,auth_epoch,method,idle_expires_at,absolute_expires_at) "
                "VALUES (%s,%s,%s,%s,'google',now()+%s*interval '1 second',now()+%s*interval '1 second')",
                (
                    owner,
                    token_digest,
                    csrf_digest,
                    state[1],
                    min(self.policy.idle_seconds, settings.session_max_age_seconds),
                    settings.session_max_age_seconds,
                ),
            )
        return self.authenticate(token_digest)

    def authenticate(
        self, token_digest: bytes, *, meaningful_activity: bool = False
    ) -> StoredSession:
        _digest(token_digest)
        with self.storage.transaction() as conn:
            row = conn.execute(
                "SELECT s.id,u.id,u.display_name,u.picture,e.address,s.csrf_digest,s.auth_epoch "
                "FROM app.sessions s JOIN app.users u ON u.id=s.user_id "
                "JOIN app.user_emails e ON e.user_id=u.id AND e.is_primary AND e.verified_at IS NOT NULL "
                "WHERE s.token_digest=%s AND s.revoked_at IS NULL AND u.status='active' "
                "AND s.auth_epoch=u.auth_epoch AND s.idle_expires_at>clock_timestamp() "
                "AND s.absolute_expires_at>clock_timestamp()",
                (token_digest,),
            ).fetchone()
            if row is None:
                raise AuthDenied("session_invalid")
            sid, owner, name, picture, email, csrf, epoch = row
            allowed, version = grant_state(conn, str(owner), self.policy)
            if meaningful_activity:
                conn.execute(
                    "UPDATE app.sessions SET last_activity_at=clock_timestamp(),"
                    "idle_expires_at=LEAST(absolute_expires_at,clock_timestamp()+%s*interval '1 second') "
                    "WHERE id=%s AND revoked_at IS NULL",
                    (self.policy.idle_seconds, sid),
                )
            return StoredSession(
                str(sid),
                {"id": str(owner), "email": email, "name": name, "picture": picture},
                bytes(csrf),
                epoch,
                self.policy.dataset_key,
                version,
                allowed,
            )

    def revoke(self, token_digest: bytes) -> None:
        _digest(token_digest)
        with self.storage.transaction() as conn:
            conn.execute(
                "UPDATE app.sessions SET revoked_at=clock_timestamp() WHERE token_digest=%s AND revoked_at IS NULL",
                (token_digest,),
            )
