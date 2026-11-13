"""Actual Linux inode protection in a disposable, narrowly mounted directory.

No monkeypatch or signing input is accepted. All key material is public fixture
data. The initializer must exit before APPEND; this signer starts afterward.
"""

import array
import errno
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from retirement.checkpoint import (
    CheckpointUnavailable,
    FS_APPEND_FL,
    FS_IOC_GETFLAGS,
    ProtectedFile,
    RECORD_BYTES,
    append_only,
)
from retirement.publisher import signed_record

DIRECTORY = Path("/fixture/authority")
SETFLAGS = 0x40086602
INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
FILES = ("checkpoints.bin", "poison.bin")


def settings(path: Path, key: Ed25519PrivateKey) -> ProtectedFile:
    """Use the current production verifier with public synthetic identity."""
    return ProtectedFile(
        path,
        owner_uid=1000,
        public_key=key.public_key().public_bytes_raw(),
        installation=INSTALLATION,
        key_id=KEY_ID,
        commitment=bytes.fromhex("11" * 32),
    )


def record(key: Ed25519PrivateKey, sequence: int, previous: bytes) -> bytes:
    """Produce real deterministic signed records, never production keys."""
    return signed_record(
        key,
        installation=INSTALLATION,
        key_id=KEY_ID,
        sequence=sequence,
        digest=bytes(32) if not sequence else bytes.fromhex("22" * 32),
        previous=previous,
        commitment=bytes.fromhex("11" * 32),
    )


def denied(name: str, action, path: Path, expected: bytes) -> str:
    """Require OS denial and an unchanged checkpoint, not merely an exception."""
    try:
        action()
    except OSError as error:
        if error.errno not in {errno.EPERM, errno.EACCES, errno.EROFS, errno.EBUSY}:
            raise AssertionError("unexpected_kernel_denial:" + name) from None
    else:
        raise AssertionError("kernel_operation_allowed:" + name)
    assert path.read_bytes() == expected, "checkpoint_changed:" + name
    return name


def initialize() -> None:
    """Exercise the production create-only initializer in a separate container."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from ops.retirement.initialize import genesis as create_genesis

    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
    values = {
        "installation": INSTALLATION,
        "key_id": KEY_ID,
        "commitment": bytes.fromhex("11" * 32),
        "public_key": key.public_key().public_bytes_raw(),
    }
    try:
        create_genesis(
            DIRECTORY, bytes.fromhex("33" * 32), **{**values, "public_key": bytes(32)}
        )
    except RuntimeError as error:
        assert str(error) == "retirement_initializer_signing_key_mismatch"
    else:
        raise AssertionError("wrong_initializer_key_wrote_authority")
    assert not list(DIRECTORY.iterdir())
    receipt = create_genesis(
        DIRECTORY,
        bytes.fromhex("33" * 32),
        installation=INSTALLATION,
        key_id=KEY_ID,
        commitment=bytes.fromhex("11" * 32),
        public_key=key.public_key().public_bytes_raw(),
    )
    raw = (DIRECTORY / "checkpoints.bin").read_bytes()
    try:
        create_genesis(DIRECTORY, bytes.fromhex("33" * 32), **values)
    except RuntimeError as error:
        assert str(error) == "retirement_initializer_requires_new_empty_authority"
    else:
        raise AssertionError("initializer_replaced_existing_authority")
    assert (DIRECTORY / "checkpoints.bin").read_bytes() == raw
    fd = os.open(
        DIRECTORY / "poison.bin",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        assert os.write(fd, raw) == RECORD_BYTES
        os.fsync(fd)
    finally:
        os.close(fd)
    (DIRECTORY / "replacement.bin").write_bytes(b"disposable replacement only")
    print(
        json.dumps(
            {
                "status": "initialized",
                "wrong_key_no_file_created": True,
                "existing_authority_never_replaced": True,
                **receipt,
            }
        ),
        flush=True,
    )


def main() -> None:
    """Attack as a new signer created only after real flag readback/setter exit."""
    assert sys.platform == "linux" and os.geteuid() == 1000
    parent = DIRECTORY.lstat()
    assert stat.S_IMODE(parent.st_mode) == 0o700 and parent.st_uid == 1000
    capabilities = dict(
        line.rstrip().split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if line.startswith(("CapEff:", "NoNewPrivs:"))
    )
    assert int(capabilities["CapEff"].strip(), 16) == 0
    assert capabilities["NoNewPrivs"].strip() == "1"
    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
    genesis = record(key, 0, bytes(32))
    path = DIRECTORY / FILES[0]
    assert path.read_bytes() == genesis
    replacement = DIRECTORY / "replacement.bin"
    append_fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC)
    checks = []
    try:
        assert append_only(append_fd), "real_ioctl_append_flag_absent"
        protected = settings(path, key)
        head = protected.head(full=True)
        assert head.sequence == 0
        checks.append("actual_GETFLAGS_and_current_ProtectedFile_genesis")

        def truncate_open() -> None:
            os.close(os.open(path, os.O_WRONLY | os.O_TRUNC))

        def nonappend_open() -> None:
            os.close(os.open(path, os.O_WRONLY | os.O_CLOEXEC))

        def nonappend_write() -> None:
            fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC)
            try:
                os.write(fd, b"overwrite")
            finally:
                os.close(fd)

        def clear_descriptor_append() -> None:
            flags = fcntl.fcntl(append_fd, fcntl.F_GETFL)
            fcntl.fcntl(append_fd, fcntl.F_SETFL, flags & ~os.O_APPEND)

        def clear_flag() -> None:
            flags = array.array("L", [0])
            fcntl.ioctl(append_fd, FS_IOC_GETFLAGS, flags, True)
            flags[0] &= ~FS_APPEND_FL
            fcntl.ioctl(append_fd, SETFLAGS, flags, True)

        attacks = (
            ("fresh_nonappend_open", nonappend_open),
            ("fresh_nonappend_write", nonappend_write),
            ("clear_descriptor_O_APPEND", clear_descriptor_append),
            ("ftruncate", lambda: os.ftruncate(append_fd, 0)),
            ("O_TRUNC", truncate_open),
            ("unlink", path.unlink),
            ("rename_checkpoint", lambda: path.rename(DIRECTORY / "renamed.bin")),
            ("rename_over_checkpoint", lambda: replacement.replace(path)),
            ("clear_append_flag_without_capability", clear_flag),
            (
                "replace_bind_mount_root",
                lambda: DIRECTORY.rename(DIRECTORY.with_name("replaced")),
            ),
        )
        checks.extend(denied(name, action, path, genesis) for name, action in attacks)
        raw = record(key, 1, head.record_digest)
        fd, before = protected._open(write=True)
        try:
            assert os.write(fd, raw) == RECORD_BYTES
            os.fsync(fd)
            protected._unchanged(fd, before, size=2 * RECORD_BYTES)
        finally:
            os.close(fd)
        assert protected.head(full=True).sequence == 1
        assert path.read_bytes()[:RECORD_BYTES] == genesis
        checks.append("real_signed208byte_append_fsync_preserves_old_prefix")
        poison = DIRECTORY / FILES[1]
        with poison.open("ab", buffering=0) as stream:
            stream.write(b"x")
            os.fsync(stream.fileno())
        try:
            settings(poison, key).head(full=True)
        except CheckpointUnavailable:
            checks.append("malicious_append_poison_fails_closed_no_repair")
        else:
            raise AssertionError("poisoned_tail_accepted")
        print(
            json.dumps(
                {
                    "status": "passed",
                    "checks": checks,
                    "kernel_append_mocked": False,
                    "preexisting_fd_revocation_claimed": False,
                    "prior_prefix_sha256": hashlib.sha256(genesis).hexdigest(),
                    "protected_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "record_bytes": RECORD_BYTES,
                    "signer_uid": os.geteuid(),
                    "signer_effective_capabilities": 0,
                    "production_inputs": False,
                    "mail_mount_proven": False,
                    "independent_SQL_composition_proven": False,
                }
            ),
            flush=True,
        )
    finally:
        os.close(append_fd)


if __name__ == "__main__":
    if sys.argv[1:] == ["--initialize"]:
        initialize()
    elif not sys.argv[1:]:
        main()
    else:
        raise RuntimeError("disposable_probe_arguments_invalid")
