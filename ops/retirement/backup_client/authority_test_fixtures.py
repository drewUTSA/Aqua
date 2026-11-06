"""Public synthetic signing keys and in-memory model data only."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import os

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

import authority_bridge as bridge
from retirement.checkpoint import DOMAIN, payload
from retirement.fingerprints import IdentityKey

RECIPIENT = "age1" + "s" * 58
STAGE = "/srv/bank-ai/.check-results/p11bc-release-20261105220000000-abcdef12"


def fixture():
    identity = IdentityKey("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", b"k" * 32)
    signer = Ed25519PrivateKey.from_private_bytes(b"s" * 32)
    installation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    def record(sequence, digest, previous):
        message = payload(
            installation,
            identity.key_id,
            sequence,
            digest,
            previous,
            identity.commitment,
        )
        return message + signer.sign(DOMAIN + message)

    genesis = record(0, bytes(32), bytes(32))
    head = record(1, b"d" * 32, hashlib.sha256(genesis).digest())
    contents = {
        "authority.dump": b"PGDMPpublic-synthetic-dump-only",
        "checkpoints.bin": genesis + head,
        "identity.key": b"k" * 32,
        "signing.key": b"s" * 32,
    }
    profile = {
        "schemaVersion": 1,
        "installation_id": installation,
        "identity_key_id": identity.key_id,
        "key_commitment": identity.commitment.hex(),
        "public_key": signer.public_key().public_bytes_raw().hex(),
        "runtime_image": "sha256:" + "a" * 64,
        "source_sha256": "b" * 64,
        "files": {name: bridge.sha(raw) for name, raw in contents.items()},
    }
    expected = bridge.Expected(
        **{
            name: profile[name]
            for name in (
                "installation_id",
                "identity_key_id",
                "key_commitment",
                "public_key",
                "runtime_image",
                "source_sha256",
            )
        },
        profile_sha256="1" * 64,
        exporter_sha256="2" * 64,
        restore_verifier_sha256="3" * 64,
        maintenance_nonce="4" * 32,
        maintenance_receipt_sha256="5" * 64,
        protected_chain_sha256=bridge.sha(contents["checkpoints.bin"]),
        head_hex=head.hex(),
    )
    raw = io.BytesIO()
    bridge.archive.write(bridge.archive.checked(contents, profile, head), raw)
    now = datetime.now(timezone.utc)
    metadata = {
        name: getattr(expected, name)
        for name in (
            "installation_id",
            "identity_key_id",
            "key_commitment",
            "public_key",
            "runtime_image",
            "source_sha256",
            "profile_sha256",
            "maintenance_nonce",
            "maintenance_receipt_sha256",
            "protected_chain_sha256",
            "head_hex",
        )
    }
    metadata.update(
        schemaVersion=1,
        mode="retained_authority_stopped_writers",
        total_host_restore_supported=False,
        sequence=1,
        event_digest=(b"d" * 32).hex(),
        checked_utc=now.isoformat(),
        maintenance_expires_utc=(now + timedelta(seconds=240)).isoformat(),
        holders_stopped={name: "absence_confirmed" for name in bridge.HOLDERS},
    )
    return expected, contents, profile, raw.getvalue(), metadata


def verifier(dump, expected, seconds):
    assert dump.startswith(b"PGDMP") and 0 < seconds <= 120
    return {
        "status": "passed",
        "mode": "synthetic_model",
        "dump_sha256": bridge.sha(dump),
        "head_sha256": bridge.sha(bytes.fromhex(expected.head_hex)),
        "runtime_image": expected.runtime_image,
        "source_sha256": expected.source_sha256,
        "verifier_source_sha256": expected.restore_verifier_sha256,
        "authority_tables": sorted(bridge.TABLES),
        "original_pages_and_floors_verified": True,
        "cleanup": "removed_and_absence_confirmed",
        "remaining_ids": [],
    }


class FakeTransport:
    def __init__(self, raw, metadata):
        self.raw, self.metadata = raw, metadata
        self.calls = []

    def head(self, *args):
        self.calls.append("head")
        return deepcopy(self.metadata)

    def encrypt(self, stage, expected, recipients, destination, seconds):
        self.calls.append("encrypt")
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "wb") as output:
            output.write(b"MODELED-CIPHERTEXT-NO-PLAINTEXT")
        return {
            "plaintext_bytes": len(self.raw),
            "plaintext_sha256": bridge.sha(self.raw),
        }

    def decrypt(self, *args):
        self.calls.append("decrypt")
        return self.raw
