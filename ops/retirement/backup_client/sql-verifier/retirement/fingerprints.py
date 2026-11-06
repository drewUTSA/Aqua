"""Private P11bc overlay: keyed canonical identity commitments, no I/O/imports.

Callers must use auth.accounts' canonical issuer/provider_observation result or
auth.password_policy.normalize_email's exact returned key. This module does not
invent another mailbox/subject normalization policy. It is not activated.
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import struct
from uuid import UUID

ISSUER = "https://accounts.google.com"
DOMAIN = b"AQUA:retirement-identity:v1\x00"


def canonical_uuid(value):
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError("retirement_identifier_invalid")
    return value


def packed(parts):
    output = bytearray(DOMAIN)
    for value in parts:
        if type(value) is not bytes or len(value) > 2048:
            raise ValueError("retirement_fingerprint_input_invalid")
        output.extend(struct.pack("!I", len(value)))
        output.extend(value)
    return bytes(output)


@dataclass(frozen=True)
class Fingerprint:
    key_id: str
    kind: str
    digest: bytes

    def __post_init__(self):
        canonical_uuid(self.key_id)
        if (
            self.kind not in {"google_subject", "mailbox"}
            or type(self.digest) is not bytes
            or len(self.digest) != 32
        ):
            raise ValueError("retirement_fingerprint_invalid")


@dataclass(frozen=True)
class IdentityKey:
    key_id: str
    material: bytes = field(repr=False)

    def __post_init__(self):
        canonical_uuid(self.key_id)
        if type(self.material) is not bytes or len(self.material) != 32:
            raise ValueError("retirement_key_invalid")

    @property
    def commitment(self):
        return hmac.new(
            self.material, b"AQUA:retirement-key-check:v1\x00", hashlib.sha256
        ).digest()

    def _commit(self, kind, values):
        message = packed((kind.encode("ascii"), *values))
        return Fingerprint(
            self.key_id,
            kind,
            hmac.new(self.material, message, hashlib.sha256).digest(),
        )

    def google(self, issuer, subject):
        if issuer != ISSUER or type(subject) is not str or not 1 <= len(subject) <= 255:
            raise ValueError("retirement_google_identity_invalid")
        try:
            values = (issuer.encode("utf-8"), subject.encode("utf-8"))
        except UnicodeEncodeError:
            raise ValueError("retirement_google_identity_invalid") from None
        return self._commit("google_subject", values)

    def mailbox(self, stored_key):
        # This is a precondition check on the stored normalized key, not a
        # replacement for either existing password/provider normalization path.
        if (
            type(stored_key) is not str
            or not 3 <= len(stored_key) <= 320
            or stored_key != stored_key.lower()
            or stored_key.count("@") != 1
            or not all(stored_key.split("@"))
            or any(ord(value) <= 32 or ord(value) == 127 for value in stored_key)
        ):
            raise ValueError("retirement_mailbox_key_invalid")
        try:
            value = stored_key.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("retirement_mailbox_key_invalid") from None
        return self._commit("mailbox", (value,))

    def google_grant_candidates(self, issuer, subject, observed_email_key):
        # Inspect both before automatic grants, even if subject approval wins.
        return (
            self.google(issuer, subject),
            self.mailbox(observed_email_key),
        )
