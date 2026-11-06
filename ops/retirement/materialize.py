"""Create-only installation inputs in a new private root, inside a cap-zero peer.

The controller must verify this exact public program before invoking it. No
initializer, publisher, application or privileged flag process exists yet.
"""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from uuid import uuid4

ROOT = Path("/home/ben2004/.aqua-runtime/retirement")
DSN = "postgresql://aqua_retirement_{}:{}@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable"


def put(path: Path, raw: bytes) -> None:
    fd = os.open(
        path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600
    )
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb", closefd=False) as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(fd)
    finally:
        os.close(fd)


def record(path: Path, value: dict) -> None:
    put(path, json.dumps(value, sort_keys=True, separators=(",", ":")).encode())


MOUNT_TARGETS = (
    "backend/checkpoints.bin",
    "backend/mail-worker.lock",
    "operator/public/checkpoints.bin",
    "operator/export/checkpoints.bin",
    "operator/export/identity.key",
    "operator/export/signing.key",
)


def mount_targets() -> None:
    """Empty create-only targets for file mounts inside read-only parent binds."""
    for relative in MOUNT_TARGETS:
        put(ROOT / relative, b"")


def create(runtime: str, source: str) -> dict:
    if (
        sys.platform != "linux"
        or os.geteuid() != 1000
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", runtime)
        or not re.fullmatch(r"[a-f0-9]{64}", source)
    ):
        raise RuntimeError("retirement_materialize_context_invalid")
    caps = next(
        line.split(":", 1)[1]
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith("CapEff:")
    )
    before = ROOT.lstat()
    if (
        int(caps.strip(), 16)
        or ROOT.resolve(strict=True) != ROOT
        or not stat.S_ISDIR(before.st_mode)
        or before.st_uid != 1000
        or stat.S_IMODE(before.st_mode) != 0o700
        or list(ROOT.iterdir())
    ):
        raise RuntimeError("retirement_materialize_requires_new_empty_root")
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    installation, key_id = str(uuid4()), str(uuid4())
    identity, seed = secrets.token_bytes(32), secrets.token_bytes(32)
    private = Ed25519PrivateKey.from_private_bytes(seed)
    commitment = hmac.new(
        identity, b"AQUA:retirement-key-check:v1\x00", hashlib.sha256
    ).hexdigest()
    common = {
        "installation_id": installation,
        "identity_key_id": key_id,
        "key_commitment": commitment,
        "public_key": private.public_key().public_bytes_raw().hex(),
    }
    public = {
        "schemaVersion": 1,
        **common,
        "runtime_image": runtime,
        "source_sha256": source,
    }
    for name in (
        "authority",
        "backend",
        "host",
        "initializer",
        "operator",
        "operator/public",
        "operator/export",
        "operator/code",
    ):
        path = ROOT / name
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
    passwords = {
        role: secrets.token_urlsafe(32)
        for role in ("writer", "checkpoint", "recovery", "backup")
    }
    record(
        ROOT / "backend/backend.json",
        {**common, "writer_dsn": DSN.format("writer", passwords["writer"])},
    )
    put(ROOT / "backend/identity.key", identity)
    # Checkpoint and backend keys never share a mounted directory.
    record(
        ROOT / "host/host.json",
        {**common, "checkpoint_dsn": DSN.format("checkpoint", passwords["checkpoint"])},
    )
    put(ROOT / "host/signing.key", seed)
    put(ROOT / "host/publisher.lock", b"")
    record(ROOT / "initializer/profile.json", {"schemaVersion": 1, **common})
    put(ROOT / "initializer/signing.key", seed)
    record(ROOT / "operator/public/verification.json", public)
    record(ROOT / "operator/export/verification.json", public)
    put(
        ROOT / "operator/export/recovery.dsn",
        DSN.format("recovery", passwords["recovery"]).encode(),
    )
    mount_targets()
    for role, password in passwords.items():
        put(ROOT / "operator" / f"{role}.password", password.encode())
    # Files and every containing directory are durable before returning. A
    # failure leaves the partial private root intact and cannot be retried.
    for name in (
        "backend",
        "host",
        "initializer",
        "operator/public",
        "operator/export",
        "operator/code",
        "operator",
        "authority",
        "",
    ):
        fd = os.open(
            ROOT / name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    if (ROOT.lstat().st_dev, ROOT.lstat().st_ino) != (before.st_dev, before.st_ino):
        raise RuntimeError("retirement_materialize_root_changed")
    return public


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--runtime-image", default="")
    parser.add_argument("--source-sha256", default="")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "keys_created": 0,
                    "writes": 0,
                }
            )
        )
        return
    print(json.dumps(create(args.runtime_image, args.source_sha256), sort_keys=True))


if __name__ == "__main__":
    main()
