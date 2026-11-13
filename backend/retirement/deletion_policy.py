"""Closed deletion scopes, irreversible generations and short metadata receipts."""

import hashlib
import hmac
import json
import re
from uuid import UUID

from retirement.fingerprints import canonical_uuid

SCOPES = {"history_delete": "chat_history_v1", "account_delete": "account_v1"}
CONFIRMATIONS = {"chat_history_v1": "DELETE HISTORY", "account_v1": "DELETE ACCOUNT"}
TOKEN = re.compile(r"v2\.[A-Za-z0-9_-]{43}\Z")
RECEIPT_HEADER = "x-aqua-deletion-receipt"
RECEIPT_SECONDS = 600
JOB_SECONDS = 3600
MAX_OWNER_JOBS = 5
MAX_JOBS = 128
MAX_PERMANENT_INTENTS = 250000
MAX_MANIFEST_BYTES = 32 * 1024 * 1024
MAX_GLOBAL_MANIFEST_BYTES = MAX_MANIFEST_BYTES
BATCH_ROWS = 32
BATCH_RESULTS = 16
WORKER_LOCK = 1095848274
STATES = frozenset({"awaiting_authority", "accepted", "purging", "complete"})


def intent_identifier(value: object) -> str:
    """Only new destructive intents/proofs require canonical RFC 4122 UUIDv4."""
    value = canonical_uuid(value)
    if UUID(value).version != 4:
        raise ValueError("deletion_intent_invalid")
    return value


def operation(scope):
    for name, value in SCOPES.items():
        if value == scope:
            return name
    raise ValueError("deletion_scope_invalid")


def target_digest(name, intent):
    if name not in SCOPES:
        raise ValueError("deletion_operation_invalid")
    intent_identifier(intent)
    raw = json.dumps(
        ["aqua-account-action-v1", name, [SCOPES[name], intent]],
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(raw).digest()


def receipt_digest(token):
    if type(token) is not str or not TOKEN.fullmatch(token):
        raise ValueError("deletion_receipt_invalid")
    return hashlib.sha256(token.encode("ascii")).digest()


def job_identifier(secret, installation, owner, intent, scope, session, receipt):
    """The independently signed Intent.job commits the exact receipt binding.

    The complete 256-bit receipt hash is separately compared on every metadata
    request. The UUID is a purpose-bound 122-bit HMAC commitment, not a bearer.
    """
    for value in (installation, owner, intent):
        canonical_uuid(value)
    if (
        type(secret) is not str
        or len(secret) < 32
        or scope not in CONFIRMATIONS
        or type(session) is not bytes
        or len(session) != 32
        or type(receipt) is not bytes
        or len(receipt) != 32
    ):
        raise ValueError("deletion_receipt_binding_invalid")
    raw = json.dumps(
        [installation, owner, intent, scope, session.hex(), receipt.hex()],
        separators=(",", ":"),
    ).encode()
    digest = hmac.new(
        secret.encode(), b"AQUA:deletion-receipt-job:v1\0" + raw, hashlib.sha256
    ).digest()
    return str(UUID(bytes=digest[:16], version=4))
