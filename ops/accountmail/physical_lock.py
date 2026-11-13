"""One fixed inode fences actual mail work across launcher/container lifetimes."""

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import os
from pathlib import Path
import stat

if __package__:
    from .private_env import Unavailable, private_directory
else:
    from private_env import Unavailable, private_directory

UID = 1000
NAME = "physical.lock"
WORKER_PATH = "/run/aqua-mail-physical/worker.lock"


def _metadata(info):
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != UID
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
        or info.st_size != 0
    ):
        raise Unavailable("unsafe_mail_physical_lock")


@dataclass(frozen=True)
class Claim:
    path: Path
    device: int
    inode: int
    fd: int = field(repr=False)

    def verify(self) -> None:
        private_directory(self.path.parent)
        if os.geteuid() != UID or self.path.resolve(strict=True) != self.path:
            raise Unavailable("unsafe_mail_physical_lock")
        actual, named = os.fstat(self.fd), self.path.lstat()
        _metadata(actual)
        _metadata(named)
        if (
            any(
                type(value) is not int or not 1 <= value <= 2**64 - 1
                for value in (self.device, self.inode)
            )
            or (actual.st_dev, actual.st_ino) != (self.device, self.inode)
            or (
                named.st_dev,
                named.st_ino,
            )
            != (self.device, self.inode)
        ):
            raise Unavailable("mail_physical_lock_replaced")

    def mount(self) -> str:
        self.verify()
        return "type=bind,src=" + str(self.path) + ",dst=" + WORKER_PATH + ",readonly"

    def environment(self) -> tuple[str, str]:
        self.verify()
        return (
            "--env=ACCOUNT_MAIL_PHYSICAL_DEVICE=" + str(self.device),
            "--env=ACCOUNT_MAIL_PHYSICAL_INODE=" + str(self.inode),
        )


def _open(directory):
    private_directory(directory)
    if os.geteuid() != UID:
        raise Unavailable("unsafe_mail_physical_lock")
    path = directory / NAME
    if path.resolve(strict=True) != path:
        raise Unavailable("unsafe_mail_physical_lock")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        info = os.fstat(fd)
        claim = Claim(path, info.st_dev, info.st_ino, fd)
        claim.verify()
        return claim
    except BaseException:
        os.close(fd)
        raise


@contextmanager
def shared(directory: Path) -> Iterator[Claim | None]:
    claim = _open(directory)
    try:
        try:
            fcntl.flock(claim.fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            yield None
        else:
            claim.verify()
            yield claim
    finally:
        os.close(claim.fd)


def prepare(directory: Path) -> None:
    """Explicit operator setup: never replace/chmod/truncate an existing inode."""
    private_directory(directory)
    if os.geteuid() != UID:
        raise Unavailable("unsafe_mail_physical_lock")
    path = directory / NAME
    try:
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
    except FileExistsError:
        pass
    else:
        try:
            os.fchmod(fd, 0o600)
            _metadata(os.fstat(fd))
            os.fsync(fd)
        finally:
            os.close(fd)
        parent = os.open(
            directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        try:
            os.fsync(parent)
        finally:
            os.close(parent)
    claim = _open(directory)
    try:
        try:
            fcntl.flock(claim.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise Unavailable("mail_physical_lock_busy") from None
        claim.verify()
    finally:
        os.close(claim.fd)
