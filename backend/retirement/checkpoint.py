"""Private checkpoint codec/reader; no key loading, files or pools open at import.

Production activation still requires actual append-only storage/mount proof.
A self-asserted tuple from either restored database is never a checkpoint.
"""

from dataclasses import dataclass
import hashlib
import hmac
import os
from pathlib import Path
import stat
import struct
import time
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from retirement.fingerprints import canonical_uuid

MAGIC = b"AQUACP1\x00"
DOMAIN = b"AQUA:retirement-checkpoint:v1\x00"
RECORD_BYTES = 208
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_SEQUENCE = 250000
ZERO = bytes(32)
FS_APPEND_FL = 0x20
FS_IOC_GETFLAGS = 0x80086601


class CheckpointUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("retirement_checkpoint_unavailable")


@dataclass(frozen=True)
class Head:
    installation: str
    key_id: str
    sequence: int
    event_digest: bytes
    previous_record: bytes
    key_commitment: bytes
    record_digest: bytes


def payload(installation, key_id, sequence, event_digest, previous, commitment):
    try:
        canonical_uuid(installation)
        canonical_uuid(key_id)
        if (
            type(sequence) is not int
            or not 0 <= sequence <= MAX_SEQUENCE
            or any(
                type(x) is not bytes or len(x) != 32
                for x in (event_digest, previous, commitment)
            )
            or sequence == 0
            and (event_digest != ZERO or previous != ZERO)
        ):
            raise ValueError
        return (
            MAGIC
            + UUID(installation).bytes
            + UUID(key_id).bytes
            + struct.pack("!Q", sequence)
            + event_digest
            + previous
            + commitment
        )
    except (ValueError, TypeError, AttributeError):
        raise CheckpointUnavailable() from None


def decode(raw, public_key, *, installation, key_id, commitment):
    if (
        type(raw) is not bytes
        or len(raw) != RECORD_BYTES
        or type(public_key) is not bytes
        or len(public_key) != 32
        or raw[:8] != MAGIC
    ):
        raise CheckpointUnavailable()
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            raw[144:], DOMAIN + raw[:144]
        )
        current = Head(
            str(UUID(bytes=raw[8:24])),
            str(UUID(bytes=raw[24:40])),
            struct.unpack("!Q", raw[40:48])[0],
            raw[48:80],
            raw[80:112],
            raw[112:144],
            hashlib.sha256(raw).digest(),
        )
        if (
            current.installation != installation
            or current.key_id != key_id
            or not hmac.compare_digest(current.key_commitment, commitment)
            or payload(
                current.installation,
                current.key_id,
                current.sequence,
                current.event_digest,
                current.previous_record,
                current.key_commitment,
            )
            != raw[:144]
        ):
            raise CheckpointUnavailable()
        return current
    except (InvalidSignature, ValueError, TypeError):
        raise CheckpointUnavailable() from None


def append_only(fd):
    # Linux's append-only inode flag is required, not inferred from an O_APPEND
    # file descriptor. Windows and unsupported/overlay filesystems fail closed.
    try:
        import array
        import fcntl

        flags = array.array("L", [0])
        fcntl.ioctl(fd, FS_IOC_GETFLAGS, flags, True)
        return bool(flags[0] & FS_APPEND_FL)
    except (ImportError, OSError, ValueError):
        return False


class ProtectedFile:
    def __init__(
        self, path, *, owner_uid, public_key, installation, key_id, commitment
    ):
        self.path = Path(path)
        self.owner_uid = owner_uid
        self.public_key = public_key
        self.installation, self.key_id, self.commitment = (
            installation,
            key_id,
            commitment,
        )
        self._startup_identity = None
        canonical_uuid(installation)
        canonical_uuid(key_id)
        if (
            not self.path.is_absolute()
            or type(owner_uid) is not int
            or owner_uid < 0
            or type(public_key) is not bytes
            or len(public_key) != 32
            or type(commitment) is not bytes
            or len(commitment) != 32
        ):
            raise CheckpointUnavailable()

    def _metadata(self, value, *, directory=False):
        required = stat.S_ISDIR if directory else stat.S_ISREG
        if (
            not required(value.st_mode)
            or value.st_uid != self.owner_uid
            or stat.S_IMODE(value.st_mode) != (0o700 if directory else 0o600)
            or not directory
            and value.st_nlink != 1
        ):
            raise CheckpointUnavailable()

    def _open(self, *, write=False):
        # This exact private parent is provisioned separately. Resolve before
        # opening and compare descriptor/path identity again after bounded I/O.
        if os.name != "posix":
            raise CheckpointUnavailable()
        parent = self.path.parent
        if (
            parent.resolve(strict=True) != parent
            or self.path.resolve(strict=True) != self.path
        ):
            raise CheckpointUnavailable()
        self._metadata(parent.lstat(), directory=True)
        before = self.path.lstat()
        self._metadata(before)
        if (
            before.st_size < RECORD_BYTES
            or before.st_size > MAX_FILE_BYTES
            or before.st_size % RECORD_BYTES
        ):
            raise CheckpointUnavailable()
        flags = os.O_WRONLY | os.O_APPEND if write else os.O_RDONLY
        flags |= os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
        fd = os.open(self.path, flags)
        try:
            actual = os.fstat(fd)
            self._metadata(actual)
            if (actual.st_dev, actual.st_ino, actual.st_size) != (
                before.st_dev,
                before.st_ino,
                before.st_size,
            ) or not append_only(fd):
                raise CheckpointUnavailable()
            return fd, actual
        except BaseException:
            os.close(fd)
            raise

    def _unchanged(self, fd, expected, *, size=None):
        actual, named = os.fstat(fd), self.path.lstat()
        self._metadata(self.path.parent.lstat(), directory=True)
        self._metadata(actual)
        self._metadata(named)
        target_size = expected.st_size if size is None else size
        if (
            (actual.st_dev, actual.st_ino, actual.st_size)
            != (expected.st_dev, expected.st_ino, target_size)
            or (named.st_dev, named.st_ino, named.st_size)
            != (actual.st_dev, actual.st_ino, actual.st_size)
            or self.path.resolve(strict=True) != self.path
            or not append_only(fd)
        ):
            raise CheckpointUnavailable()

    def _decode(self, raw):
        return decode(
            raw,
            self.public_key,
            installation=self.installation,
            key_id=self.key_id,
            commitment=self.commitment,
        )

    def head(self, *, full=False):
        """Session-gated bounded tail check; full streamed scan before startup.

        The current independently signed record is sufficient as a head anchor
        only with the actual nonrewind append-only file and verified provisioning.
        A full initial chain scan is a separate required startup prerequisite.
        """
        fd = None
        try:
            fd, before = self._open()
            identity = (before.st_dev, before.st_ino)
            if not full and self._startup_identity != identity:
                raise CheckpointUnavailable()
            count = before.st_size // RECORD_BYTES
            start = 0 if full else max(0, count - 2)
            deadline = time.monotonic() + (60 if full else 1)
            previous = None
            for index in range(start, count):
                if time.monotonic() >= deadline:
                    raise CheckpointUnavailable()
                raw = os.pread(fd, RECORD_BYTES, index * RECORD_BYTES)
                current = self._decode(raw)
                if current.sequence != index or (
                    previous is not None
                    and current.previous_record != previous.record_digest
                ):
                    raise CheckpointUnavailable()
                previous = current
            self._unchanged(fd, before)
            if time.monotonic() >= deadline:
                raise CheckpointUnavailable()
            if full:
                self._startup_identity = identity
            return previous
        except (OSError, ValueError, CheckpointUnavailable):
            raise CheckpointUnavailable() from None
        finally:
            if fd is not None:
                os.close(fd)

    def require_current(self, conn, *, allow_pending=False, full=False):
        """Must run while caller holds the common independent session gate."""
        external = self.head(full=full)
        row = conn.execute(
            "SELECT installation_id,identity_key_id,key_commitment,last_sequence,head_digest,acknowledged_sequence,acknowledged_digest,pending_count FROM retirement.checkpoint()"
        ).fetchone()
        if (
            type(row) is not tuple
            or len(row) != 8
            or str(row[0]) != external.installation
            or str(row[1]) != external.key_id
            or row[2] != external.key_commitment
            or row[3] != external.sequence
            or row[4] != external.event_digest
            or row[5] != external.sequence
            or row[6] != external.event_digest
            or type(row[7]) is not int
            or row[7] < 0
            or not allow_pending
            and row[7] != 0
        ):
            raise CheckpointUnavailable()
        return external
