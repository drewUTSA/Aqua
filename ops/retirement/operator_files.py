"""Bounded owner-only operator records; never repair or overwrite private keys."""

import hashlib
import json
import os
from pathlib import Path
import stat

PRIVATE = Path("/home/ben2004/.aqua-runtime/retirement")
MAIL = PRIVATE.parent / "mail"


def directory(path: Path) -> None:
    value = path.lstat()
    if (
        os.geteuid() != 1000
        or path.resolve(strict=True) != path
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != 1000
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise RuntimeError("retirement_operator_directory_invalid")


def read(path: Path, maximum: int = 8192) -> bytes:
    directory(path.parent)
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 1000
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= maximum
        ):
            raise RuntimeError("retirement_operator_file_invalid")
        raw = os.read(fd, maximum + 1)
        after, named = os.fstat(fd), path.lstat()
        if (
            len(raw) != before.st_size
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
            or (named.st_dev, named.st_ino) != (before.st_dev, before.st_ino)
            or path.resolve(strict=True) != path
        ):
            raise RuntimeError("retirement_operator_file_changed")
        return raw
    finally:
        os.close(fd)


def json_bytes(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def parse(raw: bytes) -> dict:
    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("retirement_operator_duplicate_field")
            result[name] = value
        return result

    value = json.loads(raw, object_pairs_hook=pairs)
    if type(value) is not dict:
        raise ValueError("retirement_operator_record_invalid")
    return value


def write_once(path: Path, raw: bytes) -> None:
    directory(path.parent)
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
    fd = os.open(
        path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    )
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def pinned(path: Path, expected: str, maximum: int = 8192) -> dict:
    raw = read(path, maximum)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("retirement_operator_profile_pin_mismatch")
    return parse(raw)
