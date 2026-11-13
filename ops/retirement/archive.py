"""Bounded plaintext-in-memory archival codec; never reads a secret or opens DB.

The enclosing controller must stream this directly into approved encryption.
Parsing an old self-consistent archive cannot establish latest-head coverage.
"""

from dataclasses import dataclass, field
import hashlib
import hmac
import io
import json
import tarfile
from typing import BinaryIO

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from retirement.checkpoint import MAX_FILE_BYTES, RECORD_BYTES, decode
from retirement.fingerprints import IdentityKey

MAX_DUMP = 128 * 1024 * 1024
MAX_PROFILE = 65536
MAX_ARCHIVE = MAX_DUMP + MAX_FILE_BYTES + 1024 * 1024
NAMES = ("authority.dump", "checkpoints.bin", "identity.key", "signing.key")


@dataclass(frozen=True)
class Bundle:
    profile: dict
    contents: dict[str, bytes] = field(repr=False)


def checked(contents: dict[str, bytes], profile: dict, expected_head: bytes) -> Bundle:
    """Validate every record/key against a separately provided protected head."""
    if (
        set(contents) != set(NAMES)
        or any(type(raw) is not bytes for raw in contents.values())
        or not 0 < len(contents["authority.dump"]) <= MAX_DUMP
        or not contents["authority.dump"].startswith(b"PGDMP")
        or not 0 < len(contents["checkpoints.bin"]) <= MAX_FILE_BYTES
        or len(contents["checkpoints.bin"]) % RECORD_BYTES
        or len(contents["identity.key"]) != 32
        or len(contents["signing.key"]) != 32
        or type(expected_head) is not bytes
        or len(expected_head) != RECORD_BYTES
        or type(profile) is not dict
        or set(profile)
        != {
            "schemaVersion",
            "installation_id",
            "identity_key_id",
            "key_commitment",
            "public_key",
            "runtime_image",
            "source_sha256",
            "files",
        }
        or profile["schemaVersion"] != 1
    ):
        raise ValueError("retirement_archive_invalid")
    key = IdentityKey(profile["identity_key_id"], contents["identity.key"])
    signer = Ed25519PrivateKey.from_private_bytes(contents["signing.key"])
    public = signer.public_key().public_bytes_raw()
    if (
        not hmac.compare_digest(key.commitment.hex(), profile["key_commitment"])
        or not hmac.compare_digest(public.hex(), profile["public_key"])
        or profile["files"]
        != {name: hashlib.sha256(contents[name]).hexdigest() for name in NAMES}
    ):
        raise ValueError("retirement_archive_key_or_content_mismatch")
    import re

    if not re.fullmatch(
        r"sha256:[a-f0-9]{64}", profile["runtime_image"]
    ) or not re.fullmatch(r"[a-f0-9]{64}", profile["source_sha256"]):
        raise ValueError("retirement_archive_source_pin_invalid")
    chain, previous = contents["checkpoints.bin"], None
    for offset in range(0, len(chain), RECORD_BYTES):
        current = decode(
            chain[offset : offset + RECORD_BYTES],
            public,
            installation=profile["installation_id"],
            key_id=key.key_id,
            commitment=key.commitment,
        )
        if (
            current.sequence != offset // RECORD_BYTES
            or previous is not None
            and current.previous_record != previous.record_digest
        ):
            raise ValueError("retirement_archive_chain_invalid")
        previous = current
    if not hmac.compare_digest(chain[-RECORD_BYTES:], expected_head):
        raise ValueError("retirement_archive_is_not_expected_protected_head")
    return Bundle(dict(profile), dict(contents))


def write(bundle: Bundle, target: BinaryIO) -> None:
    """Stream only after all bounded contents and key/chain coverage validate."""
    checked(
        bundle.contents,
        bundle.profile,
        bundle.contents["checkpoints.bin"][-RECORD_BYTES:],
    )
    profile = json.dumps(bundle.profile, sort_keys=True, separators=(",", ":")).encode()
    if len(profile) > MAX_PROFILE:
        raise ValueError("retirement_archive_profile_capacity")
    with tarfile.open(fileobj=target, mode="w|") as archive:
        for name, raw in [("profile.json", profile), *bundle.contents.items()]:
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.uid, info.gid = len(raw), 0o600, 1000, 1000
            archive.addfile(info, io.BytesIO(raw))


def read(raw: bytes, expected_head: bytes) -> Bundle:
    """No extraction, database restore or caller-chosen filesystem paths."""
    if type(raw) is not bytes or not 0 < len(raw) <= MAX_ARCHIVE:
        raise ValueError("retirement_archive_capacity")
    contents = {}
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        for item in archive:
            limit = (
                MAX_PROFILE
                if item.name == "profile.json"
                else (
                    MAX_DUMP
                    if item.name == "authority.dump"
                    else MAX_FILE_BYTES if item.name == "checkpoints.bin" else 32
                )
            )
            if (
                not item.isfile()
                or item.name not in ("profile.json", *NAMES)
                or item.name in contents
                or not 0 < item.size <= limit
            ):
                raise ValueError("retirement_archive_member_invalid")
            stream = archive.extractfile(item)
            contents[item.name] = stream.read(limit + 1)
            if len(contents[item.name]) != item.size:
                raise ValueError("retirement_archive_member_truncated")
    if set(contents) != {"profile.json", *NAMES}:
        raise ValueError("retirement_archive_incomplete")

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("retirement_archive_duplicate_profile_field")
            result[name] = value
        return result

    profile = json.loads(contents.pop("profile.json"), object_pairs_hook=pairs)
    if type(profile) is not dict:
        raise ValueError("retirement_archive_profile_invalid")
    return checked(contents, profile, expected_head)
