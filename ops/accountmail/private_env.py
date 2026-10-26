"""Strict private worker configuration and Linux singleton/snapshot helpers."""

import base64
from collections.abc import Iterator
import contextlib
import fcntl
import os
from pathlib import Path
import re
import stat

PRIVATE = Path("/home/ben2004/.aqua-runtime/mail")
FIELDS = {
    "ACCOUNT_MAIL_ENABLED",
    "ACCOUNT_MAIL_WORKER_ENABLED",
    "ACCOUNT_MAIL_OUTBOX_KEY",
    "ACCOUNT_PUBLIC_ORIGIN",
    "RESEND_API_KEY",
    "APP_STORAGE_ENABLED",
    "APP_DATABASE_URL",
    "APP_DB_POOL_SIZE",
    "APP_DB_MAX_WAITING",
    "APP_DB_WAIT_SECONDS",
}


class Unavailable(RuntimeError):
    """Fixed categories only; never attach subprocess output or configuration."""


def private_directory(directory: Path) -> None:
    if not directory.is_absolute() or directory.resolve(strict=True) != directory:
        raise Unavailable("unsafe_private_directory")
    for path in (directory.parent, directory):
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.geteuid()
            or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise Unavailable("unsafe_private_directory")


def _file_info(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise Unavailable("unsafe_private_file")


def read_environment(directory: Path) -> tuple[bytes, bool]:
    """A strict Docker env file, not shell or dotenv code; no ambient secrets."""
    fd = os.open(directory / "worker.env", os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as source:
        _file_info(os.fstat(source.fileno()))
        raw = source.read(16385)
    if len(raw) > 16384 or any(byte < 32 and byte != 10 or byte >= 127 for byte in raw):
        raise Unavailable("invalid_worker_environment")
    try:
        env = {}
        for line in raw.decode("utf-8").splitlines():
            if not line or line.startswith("#"):
                continue
            key, value = line.split("=", 1)
            if key not in FIELDS or key in env or not value:
                raise ValueError
            env[key] = value
        key = base64.b64decode(
            env["ACCOUNT_MAIL_OUTBOX_KEY"], altchars=b"-_", validate=True
        )
        if (
            set(env) != FIELDS
            or len(key) != 32
            or env["ACCOUNT_PUBLIC_ORIGIN"] != "https://aqua-ai.us"
            or env["APP_STORAGE_ENABLED"] != "true"
            or env["APP_DB_POOL_SIZE"] != "1"
            or env["APP_DB_MAX_WAITING"] != "1"
            or env["APP_DB_WAIT_SECONDS"] != "2"
            or any(
                env[name] not in {"true", "false"}
                for name in ("ACCOUNT_MAIL_ENABLED", "ACCOUNT_MAIL_WORKER_ENABLED")
            )
            or not re.fullmatch(r"re_[A-Za-z0-9_-]{8,253}", env["RESEND_API_KEY"])
            or not re.fullmatch(
                r"postgresql://aqua_app_runtime:[A-Za-z0-9_-]{40,100}@/aqua_app"
                r"\?host=/run/aqua-app-db&port=5432&sslmode=disable",
                env["APP_DATABASE_URL"],
            )
        ):
            raise ValueError
    except (KeyError, ValueError, UnicodeError):
        raise Unavailable("invalid_worker_environment") from None
    enabled = all(
        env[name] == "true"
        for name in ("ACCOUNT_MAIL_ENABLED", "ACCOUNT_MAIL_WORKER_ENABLED")
    )
    return raw, enabled


@contextlib.contextmanager
def sealed_environment(raw: bytes) -> Iterator[int]:
    """Docker reads an immutable in-memory snapshot, never a secret argv value."""
    fd = os.memfd_create("aqua-account-mail-env", os.MFD_CLOEXEC | os.MFD_ALLOW_SEALING)
    try:
        if os.write(fd, raw) != len(raw):
            raise Unavailable("environment_snapshot_failed")
        os.lseek(fd, 0, os.SEEK_SET)
        fcntl.fcntl(
            fd,
            fcntl.F_ADD_SEALS,
            fcntl.F_SEAL_WRITE
            | fcntl.F_SEAL_GROW
            | fcntl.F_SEAL_SHRINK
            | fcntl.F_SEAL_SEAL,
        )
        yield fd
    finally:
        os.close(fd)


@contextlib.contextmanager
def singleton(directory: Path) -> Iterator[bool]:
    fd = os.open(
        directory / ".launcher.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC,
        0o600,
    )
    try:
        _file_info(os.fstat(fd))
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)
