"""Narrow disposable-fixture setter; never accepts a caller-selected path."""

import array
import fcntl
import os
from pathlib import Path
import re
import stat
import sys

DIRECTORY = Path("/fixture/authority")
FILES = ("checkpoints.bin", "poison.bin")
GETFLAGS = 0x80086601
SETFLAGS = 0x40086602
APPEND = 0x20


def main() -> None:
    """Set/clear just APPEND, preserving other inode flags, for two fixed files."""
    if sys.argv[1:] not in (["set"], ["clear"]) or os.geteuid() != 0:
        raise RuntimeError("disposable_append_operation_invalid")
    parent = DIRECTORY.lstat()
    expected = tuple(
        os.environ.get(name, "")
        for name in ("AQUA_FIXTURE_DEVICE", "AQUA_FIXTURE_INODE")
    )
    if (
        DIRECTORY.resolve(strict=True) != DIRECTORY
        or not stat.S_ISDIR(parent.st_mode)
        or parent.st_uid != 1000
        or stat.S_IMODE(parent.st_mode) != 0o700
        or not all(re.fullmatch(r"[1-9][0-9]{0,19}", value) for value in expected)
        or (parent.st_dev, parent.st_ino) != tuple(map(int, expected))
    ):
        raise RuntimeError("disposable_append_directory_invalid")
    for name in FILES:
        path = DIRECTORY / name
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        try:
            info = os.fstat(fd)
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != 1000
                or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600
                or (info.st_dev, info.st_ino)
                != (path.lstat().st_dev, path.lstat().st_ino)
                or not 208 <= info.st_size <= 1024
            ):
                raise RuntimeError("disposable_append_file_invalid")
            flags = array.array("L", [0])
            fcntl.ioctl(fd, GETFLAGS, flags, True)
            flags[0] = flags[0] | APPEND if sys.argv[1] == "set" else flags[0] & ~APPEND
            fcntl.ioctl(fd, SETFLAGS, flags, True)
            actual = array.array("L", [0])
            fcntl.ioctl(fd, GETFLAGS, actual, True)
            if bool(actual[0] & APPEND) != (sys.argv[1] == "set"):
                raise RuntimeError("disposable_append_readback_failed")
            os.fsync(fd)
        finally:
            os.close(fd)


if __name__ == "__main__":
    main()
