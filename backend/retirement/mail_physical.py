"""Cross-process sender lifetime, independent of DB leases and launcher exit."""

from contextlib import contextmanager
import os
from pathlib import Path
import stat
import re

from retirement.interlock import RetirementUnavailable

WEB_PATH = Path("/run/aqua-retirement/mail-worker.lock")
WORKER_PATH = Path("/run/aqua-mail-physical/worker.lock")
FLAG = "ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED"
DEVICE = "ACCOUNT_MAIL_PHYSICAL_DEVICE"
INODE = "ACCOUNT_MAIL_PHYSICAL_INODE"
_ACTIVE = set()


class _HostClaim:
    def __init__(self, descriptor):
        self.descriptor = descriptor


def require_claim(claim):
    """Only a live successful SH context can authorize an installed sender."""
    try:
        if type(claim) is not _HostClaim or claim not in _ACTIVE:
            raise RetirementUnavailable()
        current, named = os.fstat(claim.descriptor), WORKER_PATH.lstat()
        if (current.st_dev, current.st_ino) != _expected() or (
            named.st_dev,
            named.st_ino,
        ) != (current.st_dev, current.st_ino):
            raise RetirementUnavailable()
    except OSError:
        raise RetirementUnavailable() from None


def _expected():
    values = []
    for name in (DEVICE, INODE):
        value = os.environ.get(name, "")
        if not re.fullmatch(r"[1-9][0-9]{0,19}", value) or int(value) > 2**64 - 1:
            raise RetirementUnavailable()
        values.append(int(value))
    return tuple(values)


def _open(path):
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
            parent.st_uid != 1000
            or not stat.S_ISDIR(parent.st_mode)
            or stat.S_IMODE(parent.st_mode) != 0o700
        ):
            raise RetirementUnavailable()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        current, named = os.fstat(fd), path.lstat()
        if (
            not stat.S_ISREG(current.st_mode)
            or current.st_uid != 1000
            or stat.S_IMODE(current.st_mode) != 0o600
            or current.st_nlink != 1
            or current.st_size != 0
            or (current.st_dev, current.st_ino) != (named.st_dev, named.st_ino)
            or not os.statvfs(path).f_flag & os.ST_RDONLY
        ):
            raise RetirementUnavailable()
        return fd
    except (OSError, ValueError, RetirementUnavailable):
        if fd is not None:
            os.close(fd)
        raise RetirementUnavailable() from None


def validate():
    os.close(_open(WEB_PATH))


@contextmanager
def gate(*, worker=False):
    import fcntl

    fd = _open(WORKER_PATH if worker else WEB_PATH)
    claim = None
    try:
        before = os.fstat(fd)
        if worker and (before.st_dev, before.st_ino) != _expected():
            raise RetirementUnavailable()
        try:
            fcntl.flock(
                fd, (fcntl.LOCK_SH if worker else fcntl.LOCK_EX) | fcntl.LOCK_NB
            )
        except BlockingIOError:
            yield False
        else:
            after, named = os.fstat(fd), (WORKER_PATH if worker else WEB_PATH).lstat()
            if (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino) or (
                named.st_dev,
                named.st_ino,
            ) != (before.st_dev, before.st_ino):
                raise RetirementUnavailable()
            if worker:
                claim = _HostClaim(fd)
                _ACTIVE.add(claim)
                yield claim
            else:
                yield True
    finally:
        # Closing the real descriptor releases only this physical participant.
        # A sender's own descriptor survives a dead DB session/launcher.
        if claim is not None:
            _ACTIVE.discard(claim)
        os.close(fd)
