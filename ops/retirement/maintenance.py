"""Actual stopped-writer hold; process exit never restarts writers or cron.

The enclosing reviewed release first stops the backend and pauses the exact
mail schedule. This guard verifies those facts and owns the physical locks.
"""

from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time

if __package__:
    from .operator_scope import PRODUCTION, Scope
    from .operator_files import (
        PRIVATE,
        MAIL,
        directory,
        json_bytes,
        parse,
        read,
        write_once,
    )
else:
    from operator_scope import PRODUCTION, Scope
    from operator_files import (
        PRIVATE,
        MAIL,
        directory,
        json_bytes,
        parse,
        read,
        write_once,
    )

PLAN = PRIVATE.parent / "retirement-plan.json"
STATE = PRIVATE.parent / "retirement-maintenance.json"
GLOBAL = PRIVATE.parent / "retirement-operation.lock"
FIELDS = {
    "schemaVersion",
    "runtime_image",
    "source_sha256",
    "backend_id",
    "backend_image",
    "database_id",
    "database_image",
    "paused_cron_sha256",
}
DOCKER = [
    "/usr/bin/docker",
    "--host=unix:///var/run/docker.sock",
    "--config=/proc/self/fd",
]
ENV = {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": "/proc/self/fd"}


def run(arguments: list[str], maximum: int = 16384, *, deadline=None) -> bytes:
    timeout = 10
    if deadline is not None:
        if type(deadline) not in {int, float} or not math.isfinite(deadline):
            raise RuntimeError("retirement_maintenance_probe_deadline")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise RuntimeError("retirement_maintenance_probe_deadline")
        timeout = min(timeout, remaining)
    result = subprocess.run(
        arguments,
        capture_output=True,
        timeout=timeout,
        env=ENV,
        stdin=subprocess.DEVNULL,
        close_fds=True,
    )
    if deadline is not None and time.monotonic() >= deadline:
        raise RuntimeError("retirement_maintenance_probe_deadline")
    if result.returncode or len(result.stdout) > maximum:
        raise RuntimeError("retirement_maintenance_probe_failed")
    return result.stdout


def identity(pid: int) -> dict:
    if type(pid) is not int or pid <= 1:
        raise RuntimeError("retirement_maintenance_PID_invalid")
    raw = Path(f"/proc/{pid}/stat").read_text()
    return {
        "pid": pid,
        "start_ticks": raw[raw.rindex(")") + 2 :].split()[19],
        "boot_sha256": hashlib.sha256(
            Path("/proc/sys/kernel/random/boot_id").read_bytes()
        ).hexdigest(),
    }


def plan(expected: str, scope=PRODUCTION) -> dict:
    raw = read(PLAN if scope is PRODUCTION else scope.plan)
    if (
        not re.fullmatch(r"[a-f0-9]{64}", expected)
        or hashlib.sha256(raw).hexdigest() != expected
    ):
        raise RuntimeError("retirement_maintenance_plan_pin_invalid")
    value = parse(raw)
    if (
        set(value) != FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
    ):
        raise RuntimeError("retirement_maintenance_plan_invalid")
    for name in FIELDS - {"schemaVersion"}:
        pattern = r"sha256:[a-f0-9]{64}" if name.endswith("image") else r"[a-f0-9]{64}"
        if type(value[name]) is not str or not re.fullmatch(pattern, value[name]):
            raise RuntimeError("retirement_maintenance_plan_invalid")
    return value


def stopped(
    value: dict, schema: int | None = None, scope=PRODUCTION, *, deadline=None
) -> None:
    """Inspect only curated identity/state fields, never container environments."""

    def probe(arguments, maximum=16384):
        if deadline is None:
            return run(arguments, maximum)
        return run(arguments, maximum, deadline=deadline)

    identities = (
        probe(
            [
                *DOCKER,
                "ps",
                "--all",
                "--quiet",
                "--no-trunc",
                *scope.backend_filters(),
            ]
        )
        .decode()
        .split()
    )
    if identities != [value["backend_id"]]:
        raise RuntimeError("retirement_maintenance_backend_set_changed")
    backend = probe(
        [
            *DOCKER,
            "inspect",
            value["backend_id"],
            "--format={{json .Id}}\n{{json .Image}}\n{{json .State.Running}}\n{{json .State.Pid}}\n{{json .HostConfig.PidMode}}",
        ]
    )
    if [json.loads(item) for item in backend.splitlines()] != [
        value["backend_id"],
        value["backend_image"],
        False,
        0,
        "",
    ]:
        raise RuntimeError("retirement_maintenance_web_not_stopped")
    db = probe(
        [
            *DOCKER,
            "inspect",
            value["database_id"],
            "--format={{json .Id}}\n{{json .Image}}\n{{json .State.Running}}",
        ]
    )
    if [json.loads(item) for item in db.splitlines()] != [
        value["database_id"],
        value["database_image"],
        True,
    ]:
        raise RuntimeError("retirement_maintenance_database_changed")
    if scope.qa_run is not None:
        owned = probe(
            [
                *DOCKER,
                "inspect",
                value["database_id"],
                "--format={{json .Name}}\n{{json .Config.Labels}}",
            ]
        )
        name, labels = map(json.loads, owned.splitlines())
        if (
            name != "/" + scope.qa_run + "-pg"
            or labels.get("io.aqua.run") != scope.qa_run
        ):
            raise RuntimeError("retirement_QA_database_scope_changed")
    for purpose in ("account-mail-worker", "retirement-publisher"):
        if probe(
            [
                *DOCKER,
                "ps",
                "--all",
                "--quiet",
                "--filter",
                "label=io.aqua.purpose=" + purpose,
                *scope.holder_filters(),
            ]
        ).strip():
            raise RuntimeError("retirement_maintenance_physical_holder_present")
    for name in ("aqua-account-mail-worker", "aqua-retirement-publisher"):
        if probe(
            [
                *DOCKER,
                "ps",
                "--all",
                "--quiet",
                "--filter",
                "name=^/" + scope.holder_name(name) + "$",
            ]
        ).strip():
            raise RuntimeError("retirement_maintenance_name_collision")
    if (
        hashlib.sha256(scope.schedule(probe, read)).hexdigest()
        != value["paused_cron_sha256"]
    ):
        raise RuntimeError("retirement_maintenance_schedule_changed")
    if schema is not None:
        result = probe(
            [
                *DOCKER,
                "exec",
                value["database_id"],
                "psql",
                "-X",
                "-U",
                "postgres",
                "-d",
                "aqua_app",
                "-At",
                "-c",
                "SELECT max(version) FROM app.schema_migrations",
            ]
        )
        if result.strip() != str(schema).encode():
            raise RuntimeError("retirement_maintenance_schema_mismatch")


def launcher_lock(directory: Path) -> Path:
    """The existing account-mail singleton; distinct from worker mount name."""
    return directory / ".launcher.lock"


def lock(path: Path, *, create: bool = False) -> int:
    directory(path.parent)
    flags = os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC
    if create:
        flags |= os.O_CREAT
    fd = os.open(path, flags, 0o600)
    try:
        value = os.fstat(fd)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != 1000
            or value.st_nlink != 1
            or stat.S_IMODE(value.st_mode) != 0o600
            or value.st_size != 0
            or path.resolve(strict=True) != path
            or (path.lstat().st_dev, path.lstat().st_ino)
            != (value.st_dev, value.st_ino)
        ):
            raise RuntimeError("retirement_maintenance_lock_invalid")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (path.lstat().st_dev, path.lstat().st_ino) != (value.st_dev, value.st_ino):
            raise RuntimeError("retirement_maintenance_lock_changed")
        return fd
    except BaseException:
        os.close(fd)
        raise


class Hold:
    def __init__(self, expected: str, scope=PRODUCTION):
        self.expected, self.scope = expected, scope
        self.fds = []
        self.until = time.monotonic() + 300

    @property
    def private(self):
        return PRIVATE if self.scope is PRODUCTION else self.scope.private

    @property
    def mail(self):
        return MAIL if self.scope is PRODUCTION else self.scope.mail

    @property
    def state(self):
        return STATE if self.scope is PRODUCTION else self.scope.state

    @property
    def operation(self):
        return GLOBAL if self.scope is PRODUCTION else self.scope.operation

    def __enter__(self):
        if sys.platform != "linux" or os.geteuid() != 1000:
            raise RuntimeError("retirement_maintenance_native_operator_required")
        self.scope.validate()
        self.value = plan(self.expected, self.scope)
        try:
            if self.fds or hasattr(self, "record"):
                raise RuntimeError("retirement_maintenance_holder_reused")
            self.fds.append(lock(self.operation, create=True))
            self.fds.append(lock(launcher_lock(self.mail)))
            stopped(self.value, scope=self.scope)
            # Legacy installations have only the singleton. Its EX claim and
            # actual stopped sender facts precede create-only physical setup.
            physical = self.mail / "physical.lock"
            if not physical.exists():
                write_once(physical, b"")
            self.physical_fd = lock(self.mail / "physical.lock")
            self.fds.append(self.physical_fd)
            self.publisher()
            stopped(self.value, scope=self.scope)
            self.record = {
                "schemaVersion": 1,
                "phase": "writers_stopped",
                "guard": identity(os.getpid()),
                "nonce": secrets.token_hex(16),
                "plan_sha256": self.expected,
                "expires_utc": (
                    datetime.now(timezone.utc) + timedelta(seconds=300)
                ).isoformat(),
            }
            # A stale old record is never reused: actual PID/boot and owned
            # physical locks are checked by readers for every operation.
            if self.state.exists():
                previous = parse(read(self.state))
                if previous.get("phase") == "writers_stopped":
                    try:
                        alive = identity(previous["guard"]["pid"]) == previous["guard"]
                    except (OSError, KeyError):
                        alive = False
                    if alive:
                        raise RuntimeError("retirement_maintenance_existing_guard")
                self.state.unlink()
            write_once(self.state, json_bytes(self.record))
            return self
        except BaseException:
            self.close()
            raise

    def publisher(self) -> None:
        path = self.private / "host/publisher.lock"
        if path.exists() and not getattr(self, "publisher_locked", False):
            self.fds.append(lock(path))
            self.publisher_locked = True

    def require(self, schema: int = 9) -> dict:
        if time.monotonic() >= self.until or not self.fds:
            raise RuntimeError("retirement_maintenance_expired")
        stopped(self.value, schema, scope=self.scope)
        return self.record

    def recovery_handoff(self) -> None:
        """Invalidate exports before transferring purge EX to an offline child.

        The launcher singleton, publisher and global operator EX claims stay
        held. Actual old senders have already exited, and normal launchers
        cannot create a new sender. The offline child must open its own physical
        EX descriptor; no boolean attestation can authorize its purge.
        """
        self.require(9)
        if getattr(self, "recovery_only", False) or not getattr(
            self, "publisher_locked", False
        ):
            raise RuntimeError("retirement_maintenance_recovery_handoff_invalid")
        if read(self.state) != json_bytes(self.record):
            raise RuntimeError("retirement_maintenance_attestation_changed")
        self.state.unlink()
        self.recovery_only = True
        os.close(self.physical_fd)
        self.fds.remove(self.physical_fd)

    def close(self) -> None:
        while self.fds:
            os.close(self.fds.pop())

    def __exit__(self, kind, value, traceback):
        try:
            if hasattr(self, "record") and not getattr(self, "recovery_only", False):
                # Remove only this holder's transient attestation. The caller
                # retains its separate public result; no writer is restarted.
                if read(self.state) == json_bytes(self.record):
                    self.state.unlink()
        finally:
            self.close()


def require(expected: str, schema: int = 9, scope=PRODUCTION) -> tuple[dict, dict, str]:
    scope.validate()
    value = plan(expected, scope)
    raw = read(STATE if scope is PRODUCTION else scope.state)
    state = parse(raw)
    if (
        set(state)
        != {"schemaVersion", "phase", "guard", "nonce", "plan_sha256", "expires_utc"}
        or type(state.get("schemaVersion")) is not int
        or state["schemaVersion"] != 1
        or state.get("phase") != "writers_stopped"
        or state.get("plan_sha256") != expected
        or type(state.get("nonce")) is not str
        or not re.fullmatch(r"[a-f0-9]{32}", state["nonce"])
        or type(state.get("guard")) is not dict
        or set(state["guard"]) != {"pid", "start_ticks", "boot_sha256"}
        or identity(state["guard"]["pid"]) != state["guard"]
        or datetime.now(timezone.utc) >= datetime.fromisoformat(state["expires_utc"])
    ):
        raise RuntimeError("retirement_maintenance_guard_not_live")
    for path in (
        GLOBAL if scope is PRODUCTION else scope.operation,
        launcher_lock(MAIL if scope is PRODUCTION else scope.mail),
        (MAIL if scope is PRODUCTION else scope.mail) / "physical.lock",
        (PRIVATE if scope is PRODUCTION else scope.private) / "host/publisher.lock",
    ):
        try:
            fd = lock(path)
        except BlockingIOError:
            continue
        else:
            os.close(fd)
            raise RuntimeError("retirement_maintenance_physical_lock_not_held")
    stopped(value, schema, scope=scope)
    return value, state, hashlib.sha256(raw).hexdigest()


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold", action="store_true")
    parser.add_argument("--plan-sha256", default="")
    parser.add_argument("--qa-run")
    args = parser.parse_args()
    if not args.hold:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "writes": 0,
                    "writers_restarted": False,
                }
            )
        )
        return

    def stop(signum, frame):
        raise RuntimeError("retirement_maintenance_cancelled")

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
        signal.signal(number, stop)
    signal.alarm(300)
    with Hold(
        args.plan_sha256,
        scope=Scope(args.qa_run) if args.qa_run is not None else PRODUCTION,
    ) as held:
        print(json.dumps({"status": "held", **held.record}), flush=True)
        if sys.stdin.readline().strip() != "release":
            raise RuntimeError("retirement_maintenance_controller_closed")


if __name__ == "__main__":
    main()
