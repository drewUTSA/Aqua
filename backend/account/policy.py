"""Finite account policy, independent of provider configuration and preferences."""

import hashlib
import json
import unicodedata
from uuid import UUID

MAX_REVISION = 9007199254740991
MAX_METHODS = 20
MAX_SESSIONS = 20
PROOF_SECONDS = 300
MAX_CHALLENGES = 1024
OWNER_CHALLENGES = 5
OPERATIONS = frozenset(
    {
        "email_change",
        "password_change",
        "password_add",
        "google_link",
        "google_unlink",
        "session_revoke",
        "sessions_revoke_all",
        "data_export",
    }
)
CAPABILITIES = {
    "profile_edit": True,
    "method_list": True,
    "session_list": True,
    "recent_proof": False,
    "email_change": False,
    "password_change": False,
    "password_add": False,
    "google_link": False,
    "google_unlink": False,
    "session_revoke": False,
    "sessions_revoke_all": False,
    "notification_delivery": False,
    "in_app_notifications": True,
}


def display_name(value: object) -> str:
    """Plain single-line Unicode text; neither markup nor a provider image URL."""
    if type(value) is not str:
        raise ValueError("account_profile_invalid")
    if any(
        unicodedata.category(char).startswith("C")
        or unicodedata.category(char) in {"Zl", "Zp"}
        for char in value
    ):
        raise ValueError("account_profile_invalid")
    value = unicodedata.normalize("NFC", value).strip()
    if (
        not 1 <= len(value) <= 120
        or len(value.encode("utf-8")) > 512
        or any(
            unicodedata.category(char).startswith("C")
            or unicodedata.category(char) in {"Zl", "Zp"}
            for char in value
        )
    ):
        raise ValueError("account_profile_invalid")
    return value


def identifier(value: object) -> str:
    if type(value) is not str:
        raise ValueError("account_target_invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("account_target_invalid") from None
    if str(parsed) != value:
        raise ValueError("account_target_invalid")
    return value


def target_digest(operation: object, target: object = None) -> bytes:
    """Canonical, domain-separated binding from server-selected action targets.

    No public route accepts a target digest. The future email service must pass
    its already-normalized mailbox; the future password action targets this
    account, never a caller-selected credential or owner.
    """
    if type(operation) is not str or operation not in OPERATIONS:
        raise ValueError("account_operation_invalid")
    if operation == "data_export":
        from privacy.policy import target_digest as export_target

        return export_target(target)
    if operation in {"google_unlink", "session_revoke"}:
        target = identifier(target)
    elif operation in {"email_change", "password_add"}:
        if (
            type(target) is not str
            or not 3 <= len(target) <= 320
            or not target.isascii()
            or target != target.lower()
            or target.count("@") != 1
            or not all(target.split("@"))
            or any(ord(char) <= 32 or ord(char) == 127 for char in target)
        ):
            raise ValueError("account_target_invalid")
    elif target is not None:
        raise ValueError("account_target_invalid")
    encoded = json.dumps(
        ["aqua-account-action-v1", operation, target], separators=(",", ":")
    )
    return hashlib.sha256(encoded.encode("utf-8")).digest()


def digest(value: object) -> bytes:
    if type(value) is not bytes or len(value) != 32:
        raise ValueError("account_proof_invalid")
    return value


def device_label(value: object) -> str:
    """Stored coarse labels are untrusted; never infer location or read raw UA."""
    if (
        type(value) is not str
        or len(value) > 120
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        return "Unknown device"
    return value.strip() or "Unknown device"
