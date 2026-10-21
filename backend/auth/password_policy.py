"""Versioned local-password policy; no password or mailbox leaves this process."""

from dataclasses import dataclass
import re
import unicodedata

from auth.config import AuthDenied
from auth.password_blocklist import is_common

# A local, versioned common-password blocklist. This intentionally does not send
# user secrets to a breach API; it is not a complete corpus of breached secrets.
BLOCKED = frozenset(
    {
        "passwordpassword",
        "password123456789",
        "password12345678",
        "password1234567",
        "password123456",
        "password1234567890",
        "123456789012345",
        "1234567890123456",
        "12345678901234567890",
        "qwertyuiopasdfgh",
        "qwertyuiopasdfghjkl",
        "qwerty1234567890",
        "letmeinletmein123",
        "adminadminadmin",
        "administrator123",
        "correct horse battery staple",
        "this is my password",
        "iloveyouiloveyou",
        "welcome123456789",
        "changeme12345678",
        "defaultpassword123",
        "aaaaaaaaaaaaaaa",
        "111111111111111",
        "000000000000000",
    }
)
EMAIL = re.compile(r"[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+\Z")
TOKEN = re.compile(r"[A-Za-z0-9_-]{43}\Z")


@dataclass(frozen=True)
class PasswordPolicy:
    version: int = 1
    verification_seconds: int = 86400
    reset_seconds: int = 1800
    window_seconds: int = 60
    login_peer_limit: int = 10
    login_global_limit: int = 30
    login_address_limit: int = 5
    mail_peer_limit: int = 5
    mail_global_limit: int = 30
    mail_address_limit: int = 3
    consume_peer_limit: int = 10
    consume_global_limit: int = 30
    max_admission_keys: int = 2048
    max_challenges: int = 4096
    cleanup_batch: int = 64
    max_hashes: int = 2

    def __post_init__(self) -> None:
        bounds = (
            (self.version, 1, 1),
            (self.verification_seconds, 60, 86400),
            (self.reset_seconds, 60, 1800),
            (self.window_seconds, 1, 60),
            (self.max_admission_keys, 8, 4096),
            (self.max_challenges, 8, 8192),
            (self.cleanup_batch, 1, 128),
            (self.max_hashes, 1, 2),
        )
        rates = (
            self.login_peer_limit,
            self.login_global_limit,
            self.login_address_limit,
            self.mail_peer_limit,
            self.mail_global_limit,
            self.mail_address_limit,
            self.consume_peer_limit,
            self.consume_global_limit,
        )
        if any(
            type(value) is not int or not low <= value <= high
            for value, low, high in bounds
        ):
            raise ValueError("password_policy_invalid")
        if any(type(value) is not int or not 1 <= value <= 300 for value in rates):
            raise ValueError("password_policy_invalid")


def normalize_email(value: str) -> str:
    """P04 supports ASCII mailboxes, with P03's case-insensitive exact key.

    Reject internationalized mailbox syntax until both Google backfill and the
    sender explicitly support one audited normalization policy. Preserve dots
    and plus suffixes; never guess that two addresses identify the same person.
    """
    if (
        not isinstance(value, str)
        or not 3 <= len(value) <= 254
        or not EMAIL.fullmatch(value)
    ):
        raise AuthDenied("email_invalid")
    local, domain = value.rsplit("@", 1)
    labels = domain.split(".")
    if (
        len(local) > 64
        or local.startswith(".")
        or local.endswith(".")
        or ".." in local
        or len(labels) < 2
        or any(
            not part or len(part) > 63 or part.startswith("-") or part.endswith("-")
            for part in labels
        )
    ):
        raise AuthDenied("email_invalid")
    return value.lower()


def normalize_password(value: str, *, establish: bool = True) -> str:
    """NFC is applied identically at establishment and verification; never truncate."""
    if not isinstance(value, str) or len(value) > 512:
        raise AuthDenied("password_invalid")
    normalized = unicodedata.normalize("NFC", value)
    if (
        not 15 <= len(normalized) <= 128
        or any(unicodedata.category(char) in {"Cc", "Cs"} for char in normalized)
        or len(normalized.encode("utf-8")) > 512
    ):
        raise AuthDenied("password_invalid")
    if establish and (
        normalized.casefold() in BLOCKED
        or len(set(normalized)) < 3
        or is_common(normalized)
    ):
        raise AuthDenied("password_invalid")
    return normalized


def validate_token(value: str) -> None:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise AuthDenied("email_challenge_invalid")
