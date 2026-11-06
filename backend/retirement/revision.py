"""Opaque owner/history publication revision, never an authorization token."""

import hashlib
import hmac
import struct
from uuid import UUID

from retirement.fingerprints import canonical_uuid

DOMAIN = b"AQUA:history-publication:v1\x00"


def history_revision(secret, owner, generation):
    # Inputs are existing checked server settings/current guarded user values.
    # Never accept an epoch or secret from a request or persist this in app data.
    canonical_uuid(owner)
    if (
        type(secret) is not str
        or not 32 <= len(secret) <= 4096
        or type(generation) is not int
        or not 1 <= generation <= 9007199254740991
    ):
        raise ValueError("history_revision_unavailable")
    try:
        key = secret.encode("utf-8")
    except UnicodeEncodeError:
        raise ValueError("history_revision_unavailable") from None
    return hmac.new(
        key, DOMAIN + UUID(owner).bytes + struct.pack("!Q", generation), hashlib.sha256
    ).hexdigest()
