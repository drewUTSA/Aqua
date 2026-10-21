"""Keep credentials outside the shared checkout; never print secret values."""

import json
import os
from pathlib import Path
import re
import secrets
import stat

PRIVATE = Path("/home/ben2004/.aqua-runtime/app-storage")


def directory() -> Path:
    if os.geteuid() != 1000:
        raise RuntimeError("run as the existing AQUA operator without sudo")
    for path in [Path("/home"), Path("/home/ben2004"), PRIVATE.parent, PRIVATE]:
        if not path.exists() and path in {PRIVATE.parent, PRIVATE}:
            path.mkdir(mode=0o700)
        info = path.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid not in {0, 1000}
            or info.st_mode & 0o022
        ):
            raise RuntimeError("unsafe private credential directory")
        if path in {PRIVATE.parent, PRIVATE} and (
            info.st_uid != 1000 or stat.S_IMODE(info.st_mode) != 0o700
        ):
            raise RuntimeError("private credential directory must be owner-only")
    return PRIVATE


def read(name: str, mode: int = 0o600) -> bytes:
    path = directory() / name
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.geteuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != mode
        or info.st_size > 8192
    ):
        raise RuntimeError("unsafe credential file")
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW), "rb") as source:
        return source.read(8193)


def write_once(name: str, value: bytes, mode: int = 0o600) -> None:
    path = directory() / name
    if path.exists():
        if read(name, mode) != value:
            raise RuntimeError(
                "existing private file differs; review without replacement"
            )
        return
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as target:
        os.fchmod(target.fileno(), mode)
        target.write(value)
        target.flush()
        os.fsync(target.fileno())


def credentials() -> dict[str, str]:
    data = json.loads(read("credentials.json"))
    if set(data) != {"bootstrap", "runtime", "migrator", "backup"} or any(
        not re.fullmatch(r"[A-Za-z0-9_-]{40,100}", value) for value in data.values()
    ):
        raise RuntimeError("unexpected credential document")
    return data


def prepare() -> None:
    if not (directory() / "credentials.json").exists():
        data = {
            name: secrets.token_urlsafe(32)
            for name in ("bootstrap", "runtime", "migrator", "backup")
        }
        write_once("credentials.json", json.dumps(data).encode())
    data = credentials()
    # The host parent is 0700. This one mounted file must also be readable by
    # the non-root postgres UID inside its private container; no public bind.
    write_once("bootstrap-password", data["bootstrap"].encode(), 0o444)
    for name in ("runtime", "migrator"):
        key = "APP_DATABASE_URL" if name == "runtime" else "APP_MIGRATOR_DATABASE_URL"
        value = f"{key}=postgresql://aqua_app_{name}:{data[name]}@/aqua_app?host=/run/aqua-app-db&port=5432&sslmode=disable\n"
        if name == "runtime":
            value = "APP_STORAGE_ENABLED=false\n" + value
        write_once(name + ".env", value.encode())
