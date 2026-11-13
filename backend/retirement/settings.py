"""Read only separately provisioned, owner-only retirement verification inputs."""

from dataclasses import dataclass, field
import json
import os
from pathlib import Path
import re
import stat

from retirement.fingerprints import IdentityKey, canonical_uuid
from retirement.interlock import RetirementUnavailable

DIRECTORY = Path("/run/aqua-retirement")
FLAG = "PRIVATE_DATA_DELETE_ENABLED"
FIELDS = frozenset(
    {"installation_id", "identity_key_id", "key_commitment", "public_key", "writer_dsn"}
)
DSN = re.compile(
    r"postgresql://aqua_retirement_writer:[A-Za-z0-9_-]{43}@/aqua_retirement\?host=/run/aqua-app-db&port=5432&sslmode=disable\Z"
)


@dataclass(frozen=True)
class Settings:
    installation: str
    identity: IdentityKey = field(repr=False)
    public_key: bytes
    dsn: str = field(repr=False)


def private_bytes(path, maximum, *, exact=None):
    """Never allocate or follow a link before validating this private mount."""
    fd = None
    try:
        if (
            os.name != "posix"
            or os.geteuid() != 1000
            or path.resolve(strict=True) != path
        ):
            raise RetirementUnavailable()
        parent = path.parent.lstat()
        if (
            not stat.S_ISDIR(parent.st_mode)
            or parent.st_uid != 1000
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise RetirementUnavailable()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 1000
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= maximum
            or exact is not None
            and before.st_size != exact
        ):
            raise RetirementUnavailable()
        raw = os.read(fd, maximum + 1)
        after, named = os.fstat(fd), path.lstat()
        if (
            len(raw) != before.st_size
            or (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_uid,
                after.st_nlink,
                stat.S_IMODE(after.st_mode),
            )
            != (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                1000,
                1,
                0o600,
            )
            or (
                named.st_dev,
                named.st_ino,
                named.st_uid,
                named.st_nlink,
                stat.S_IMODE(named.st_mode),
            )
            != (before.st_dev, before.st_ino, 1000, 1, 0o600)
            or path.resolve(strict=True) != path
            or path.parent.lstat().st_uid != 1000
            or stat.S_IMODE(path.parent.lstat().st_mode) != 0o700
        ):
            raise RetirementUnavailable()
        return raw
    except (OSError, ValueError):
        raise RetirementUnavailable() from None
    finally:
        if fd is not None:
            os.close(fd)


def _pairs(items):
    result = {}
    for name, value in items:
        if name in result:
            raise RetirementUnavailable()
        result[name] = value
    return result


def parse(raw, identity_bytes):
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
        if (
            type(value) is not dict
            or set(value) != FIELDS
            or any(type(item) is not str for item in value.values())
            or not DSN.fullmatch(value["writer_dsn"])
            or any(
                not re.fullmatch(r"[a-f0-9]{64}", value[key])
                for key in ("key_commitment", "public_key")
            )
        ):
            raise RetirementUnavailable()
        key = IdentityKey(value["identity_key_id"], identity_bytes)
        if key.commitment.hex() != value["key_commitment"]:
            raise RetirementUnavailable()
        return Settings(
            canonical_uuid(value["installation_id"]),
            key,
            bytes.fromhex(value["public_key"]),
            value["writer_dsn"],
        )
    except (ValueError, TypeError, UnicodeError):
        raise RetirementUnavailable() from None


def load():
    if os.environ.get(FLAG, "false") not in {"true", "false"}:
        raise RetirementUnavailable()
    # The persistent mount, not a restored application row, decides whether the
    # authority is installed. Turning the UI operation off keeps this verification.
    present = (DIRECTORY / "backend.json").exists()
    if not present and os.environ.get(FLAG, "false") == "false":
        return None
    try:
        if not os.statvfs(DIRECTORY).f_flag & os.ST_RDONLY:
            raise RetirementUnavailable()
    except OSError:
        raise RetirementUnavailable() from None
    return parse(
        private_bytes(DIRECTORY / "backend.json", 4096),
        private_bytes(DIRECTORY / "identity.key", 32, exact=32),
    )
