"""Create-only genesis writer, separate from every admitted signing process.

The invoking controller must remove/absence-confirm this initializer process
before setting APPEND, and create the signer only after setter exit/readback.
Linux APPEND does not revoke a previously opened nonappend writer descriptor.
"""

import hashlib
import hmac
import json
import argparse
import os
from pathlib import Path
import stat
import sys

INPUTS = Path("/run/aqua-retirement-initializer")
AUTHORITY = Path("/run/aqua-retirement-authority")


def execute() -> dict:
    """Read only a separate pinned initializer mount, never backend credentials."""
    from retirement.settings import private_bytes

    if not os.statvfs(INPUTS).f_flag & os.ST_RDONLY:
        raise RuntimeError("retirement_initializer_inputs_must_be_readonly")

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("retirement_initializer_duplicate_profile_field")
            result[name] = value
        return result

    value = json.loads(
        private_bytes(INPUTS / "profile.json", 4096), object_pairs_hook=pairs
    )
    fields = {
        "schemaVersion",
        "installation_id",
        "identity_key_id",
        "key_commitment",
        "public_key",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or any(type(value[name]) is not str for name in fields - {"schemaVersion"})
    ):
        raise RuntimeError("retirement_initializer_profile_invalid")
    import re

    if any(
        not re.fullmatch(r"[a-f0-9]{64}", value[name])
        for name in ("key_commitment", "public_key")
    ):
        raise RuntimeError("retirement_initializer_profile_invalid")
    return genesis(
        AUTHORITY,
        private_bytes(INPUTS / "signing.key", 32, exact=32),
        installation=value["installation_id"],
        key_id=value["identity_key_id"],
        commitment=bytes.fromhex(value["key_commitment"]),
        public_key=bytes.fromhex(value["public_key"]),
    )


def genesis(
    directory: Path,
    seed: bytes,
    *,
    installation: str,
    key_id: str,
    commitment: bytes,
    public_key: bytes,
) -> dict:
    """Refuse existing authority; fsync and close every fd before returning."""
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from retirement.publisher import signed_record

    if (
        os.geteuid() != 1000
        or sys.platform != "linux"
        or type(seed) is not bytes
        or len(seed) != 32
    ):
        raise RuntimeError("retirement_initializer_context_invalid")
    capability = next(
        line.split(":", 1)[1]
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith("CapEff:")
    )
    if int(capability.strip(), 16) != 0:
        raise RuntimeError("retirement_initializer_capabilities_forbidden")
    parent = directory.lstat()
    if (
        directory.resolve(strict=True) != directory
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != 1000
        or stat.S_IMODE(parent.st_mode) != 0o700
        or list(directory.iterdir())
    ):
        raise RuntimeError("retirement_initializer_requires_new_empty_authority")
    private = Ed25519PrivateKey.from_private_bytes(seed)
    if not hmac.compare_digest(private.public_key().public_bytes_raw(), public_key):
        raise RuntimeError("retirement_initializer_signing_key_mismatch")
    raw = signed_record(
        private,
        installation=installation,
        key_id=key_id,
        sequence=0,
        digest=bytes(32),
        previous=bytes(32),
        commitment=commitment,
    )
    path = directory / "checkpoints.bin"
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        os.fchmod(fd, 0o600)
        current = os.fstat(fd)
        if current.st_uid != 1000 or current.st_nlink != 1:
            raise RuntimeError("retirement_initializer_file_invalid")
        if os.write(fd, raw) != len(raw):
            raise RuntimeError("retirement_initializer_partial_write")
        os.fsync(fd)
        named = path.lstat()
        if (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino):
            raise RuntimeError("retirement_initializer_inode_changed")
    finally:
        os.close(fd)
    parent_fd = os.open(
        directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        current_parent = os.fstat(parent_fd)
        if (current_parent.st_dev, current_parent.st_ino) != (
            parent.st_dev,
            parent.st_ino,
        ):
            raise RuntimeError("retirement_initializer_parent_changed")
        os.fsync(parent_fd)
    finally:
        os.close(parent_fd)
    return {
        "device": named.st_dev,
        "inode": named.st_ino,
        "genesis_sha256": hashlib.sha256(raw).hexdigest(),
        "initializer_exit_required_before_flag": True,
        "signer_admitted": False,
    }


def main() -> None:
    """No default secret reads, file creation, key generation or signer start."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    arguments = parser.parse_args()
    if arguments.execute:
        print(json.dumps(execute(), sort_keys=True))
        return
    print(
        json.dumps(
            {
                "status": "prepared_only",
                "private_reads": 0,
                "writes": 0,
                "requires_new_empty_authority": True,
                "initializer_exit_before_flag": True,
                "signer_created_after_flag_readback_and_setter_exit": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
