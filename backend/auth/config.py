"""Server-owned identity policy, independent of Google provider availability."""

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import json
import os

from nl2sql.config import Settings


class AuthDenied(RuntimeError):
    """A fixed denial category; caller never serializes a driver exception."""


class AuthLimited(RuntimeError):
    def __init__(self, retry_after: int = 60) -> None:
        super().__init__("authentication_rate_limited")
        self.retry_after = max(1, min(retry_after, 600))


def dataset_key(settings: Settings) -> str:
    """Match P01's dataset namespace without returning its connection string."""
    raw = json.dumps(settings.database_url, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class AuthPolicy:
    dataset_key: str = ""
    allowed_emails: frozenset[str] = field(default_factory=frozenset, repr=False)
    allowed_google_subs: frozenset[str] = field(default_factory=frozenset, repr=False)
    max_sessions: int = 5
    idle_seconds: int = 1800
    challenge_seconds: int = 600
    window_seconds: int = 60
    challenge_peer_limit: int = 10
    challenge_global_limit: int = 60
    login_peer_limit: int = 10
    login_global_limit: int = 30
    login_account_limit: int = 5
    action_global_limit: int = 30
    action_account_limit: int = 5
    max_admission_keys: int = 2048
    cleanup_batch: int = 64

    def __post_init__(self) -> None:
        limits = (
            (self.max_sessions, 1, 20),
            (self.idle_seconds, 60, 3600),
            (self.challenge_seconds, 60, 600),
            (self.window_seconds, 1, 60),
            (self.max_admission_keys, 8, 4096),
            (self.cleanup_batch, 1, 128),
        )
        rates = (
            self.challenge_peer_limit,
            self.challenge_global_limit,
            self.login_peer_limit,
            self.login_global_limit,
            self.login_account_limit,
            self.action_global_limit,
            self.action_account_limit,
        )
        if any(type(v) is not int or not lo <= v <= hi for v, lo, hi in limits):
            raise ValueError("authentication_policy_invalid")
        if any(type(v) is not int or not 1 <= v <= 300 for v in rates):
            raise ValueError("authentication_policy_invalid")
        if self.dataset_key and (
            len(self.dataset_key) != 64
            or any(char not in "0123456789abcdef" for char in self.dataset_key)
        ):
            raise ValueError("authentication_dataset_invalid")


def load_auth_policy(
    settings: Settings, environ: Mapping[str, str] | None = None
) -> AuthPolicy:
    """Only bounded operator choices; browser preferences never set limits."""
    env = os.environ if environ is None else environ
    try:
        return AuthPolicy(
            dataset_key=dataset_key(settings) if settings.database_url else "",
            allowed_emails=settings.auth_allowed_emails,
            allowed_google_subs=settings.auth_allowed_google_subs,
            max_sessions=int(env.get("AUTH_MAX_SESSIONS", "5")),
            idle_seconds=int(env.get("AUTH_IDLE_SECONDS", "1800")),
        )
    except (TypeError, ValueError):
        raise ValueError("authentication_configuration_invalid") from None
