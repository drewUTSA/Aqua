"""Password workflows share durable policy and never infer analytical entitlement."""

import time

from auth.config import AuthDenied, AuthPolicy, dataset_key
from auth.mailconfig import MailPolicy
from auth.password_email import request_email
from auth.password_hash import PasswordHasher
from auth.password_limits import hash_slot, reserve
from auth.password_policy import (
    PasswordPolicy,
    normalize_email,
    normalize_password,
    validate_token,
)
from auth.password_records import (
    create_verified_account,
    find_candidate,
    find_ticket,
    replace_password,
)
from auth.password_sessions import create_session
from auth.store import IdentityStore, StoredSession
from nl2sql.config import Settings
from storage.pool import Storage


class PasswordStore:
    def __init__(
        self,
        storage: Storage,
        auth_policy: AuthPolicy,
        password_policy: PasswordPolicy = PasswordPolicy(),
        mail_policy: MailPolicy = MailPolicy(),
        *,
        hasher: PasswordHasher | None = None,
    ) -> None:
        self.storage = storage
        self.auth_policy = auth_policy
        self.policy = password_policy
        self.mail_policy = mail_policy
        self.hasher = hasher or PasswordHasher()

    @property
    def password_policy(self) -> PasswordPolicy:
        return self.policy

    @password_policy.setter
    def password_policy(self, value: PasswordPolicy) -> None:
        self.policy = value

    def request_email(self, email: str, purpose: str, peer_key: str) -> None:
        if purpose not in {"verify_email", "password_reset"}:
            raise AuthDenied("email_challenge_invalid")
        email = normalize_email(email)
        reserve(self.storage, self.policy, "mail", peer_key, email)
        started = time.monotonic()
        request_email(self.storage, self.policy, self.mail_policy, email, purpose)
        # Admission bounds accepted work to 30/min globally. Pad only generic
        # success after releasing the DB lease; rejected floods never sleep.
        remaining = 0.05 - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)

    def complete_verification(self, token: str, password: str, peer_key: str) -> str:
        reserve(self.storage, self.policy, "consume", peer_key)
        validate_token(token)
        password = normalize_password(password)
        with self.storage.transaction() as conn:
            ticket = find_ticket(conn, token, "verify_email")
        with hash_slot(self.storage, self.policy):
            encoded = self.hasher.hash(password)
        with self.storage.transaction() as conn:
            return create_verified_account(conn, ticket, encoded, self.policy.version)

    def reset_password(self, token: str, password: str, peer_key: str) -> None:
        reserve(self.storage, self.policy, "consume", peer_key)
        validate_token(token)
        password = normalize_password(password)
        with self.storage.transaction() as conn:
            ticket = find_ticket(conn, token, "password_reset")
        with hash_slot(self.storage, self.policy):
            encoded = self.hasher.hash(password)
        with self.storage.transaction() as conn:
            replace_password(
                conn, ticket, encoded, self.policy.version, self.mail_policy
            )

    def login(
        self,
        email: str,
        password: str,
        token_digest: bytes,
        csrf_digest: bytes,
        peer_key: str,
        settings: Settings,
    ) -> StoredSession:
        email = normalize_email(email)
        reserve(self.storage, self.policy, "login", peer_key, email)
        expected = dataset_key(settings) if settings.database_url else ""
        if (
            self.auth_policy.dataset_key != expected
            or not 300 <= settings.session_max_age_seconds <= 86400
        ):
            raise AuthDenied("authentication_policy_mismatch")
        if any(
            not isinstance(value, bytes) or len(value) != 32
            for value in (token_digest, csrf_digest)
        ):
            raise AuthDenied("authentication_token_invalid")
        # Invalid policy input is bounded before Argon2. Valid-length failures,
        # absent users, disabled users and Google-only users all verify a hash.
        password = normalize_password(password, establish=False)
        with self.storage.transaction() as conn:
            candidate = find_candidate(conn, email)
        encoded = candidate.encoded if candidate and candidate.active else None
        with hash_slot(self.storage, self.policy):
            accepted = self.hasher.verify(password, encoded)
            replacement = (
                self.hasher.hash(password)
                if accepted and self.hasher.needs_rehash(encoded)
                else None
            )
        if not accepted or candidate is None or not candidate.active:
            raise AuthDenied("password_credentials_invalid")
        with self.storage.transaction() as conn:
            create_session(
                conn,
                candidate,
                email,
                replacement,
                token_digest,
                csrf_digest,
                self.auth_policy,
                settings,
            )
        return IdentityStore(self.storage, self.auth_policy).authenticate(token_digest)
