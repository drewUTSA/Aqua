"""No Docker/provider calls: real flock handoff and closed host launch metadata."""

import fcntl
import json
import os
from pathlib import Path
import select
import signal
import subprocess
import sys
import time

import pytest

from ops.accountmail import docker_worker, launch as launcher, physical_lock
from ops.accountmail.private_env import retirement_enabled
from test_account_mail_launcher import (
    FakeDocker,
    IDENT,
    environment,
    install_fake,
    private as private,
    write_environment,
)


def exclusive(path):
    fd = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True
    finally:
        os.close(fd)


@pytest.fixture
def protected(private):
    if sys.platform != "linux" or os.geteuid() != 1000:
        pytest.skip("physical launch proof runs in the isolated uid1000 Linux runner")
    physical_lock.prepare(private)
    write_environment(private, environment(ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED="true"))
    return private


def test_new_flag_is_closed_boolean_and_absence_preserves_legacy_environment(private):
    assert not retirement_enabled(environment())
    assert not retirement_enabled(
        environment(ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED="false")
    )
    assert retirement_enabled(environment(ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED="true"))
    for value in ["TRUE", "1", "yes", "true false", ""]:
        with pytest.raises(launcher.Unavailable):
            retirement_enabled(environment(ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED=value))
    for name in [
        "ACCOUNT_MAIL_PHYSICAL_DEVICE",
        "ACCOUNT_MAIL_PHYSICAL_INODE",
        "DATABASE_URL",
    ]:
        write_environment(private, environment(**{name: "123"}))
        with pytest.raises(launcher.Unavailable):
            launcher.read_environment(private)


def test_prepare_is_create_only_and_never_replaces_or_truncates_an_existing_inode(
    protected,
):
    path = protected / physical_lock.NAME
    before = path.stat()
    physical_lock.prepare(protected)
    assert (path.stat().st_dev, path.stat().st_ino) == (before.st_dev, before.st_ino)
    assert before.st_uid == 1000 and before.st_mode & 0o777 == 0o600
    assert before.st_nlink == 1 and before.st_size == 0
    with physical_lock.shared(protected) as claim:
        assert claim and not exclusive(path)
        with pytest.raises(launcher.Unavailable, match="mail_physical_lock_busy"):
            physical_lock.prepare(protected)
        with launcher.singleton(protected) as singleton:
            assert singleton  # The ordinary overlap lock is a different inode.
    path.write_bytes(b"x")
    with pytest.raises(launcher.Unavailable):
        physical_lock.prepare(protected)
    assert path.read_bytes() == b"x" and path.stat().st_ino == before.st_ino


@pytest.mark.parametrize(
    "kind", ["missing", "symlink", "fifo", "hardlink", "mode", "size", "parent", "uid"]
)
def test_unsafe_physical_lock_fails_before_any_docker_admission(
    protected, monkeypatch, kind
):
    path = protected / physical_lock.NAME
    if kind in {"missing", "symlink", "fifo"}:
        path.unlink()
    if kind == "symlink":
        path.symlink_to(protected / "worker.env")
    elif kind == "fifo":
        os.mkfifo(path, 0o600)
    elif kind == "hardlink":
        os.link(path, protected / "second-lock")
    elif kind == "mode":
        path.chmod(0o640)
    elif kind == "size":
        path.write_bytes(b"x")
    elif kind == "parent":
        protected.chmod(0o750)
    elif kind == "uid":
        monkeypatch.setattr(physical_lock, "UID", 1001)
    admitted = []
    monkeypatch.setattr(launcher, "host_ready", lambda: admitted.append(True))
    with pytest.raises((OSError, launcher.Unavailable)):
        launcher.launch(protected)
    assert not admitted


def test_shared_claim_allows_real_worker_handoff_but_excludes_purge_until_both_exit(
    protected,
):
    path = protected / physical_lock.NAME
    with physical_lock.shared(protected) as first:
        with physical_lock.shared(protected) as second:
            assert first and second and first.inode == second.inode
            assert not exclusive(path)
        assert not exclusive(path)
    assert exclusive(path)


def test_real_exclusive_purge_blocks_launcher_before_create_without_touching_mail(
    protected, monkeypatch
):
    fd = os.open(protected / physical_lock.NAME, os.O_RDONLY | os.O_CLOEXEC)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        monkeypatch.setattr(
            launcher, "host_ready", lambda: pytest.fail("Docker was admitted")
        )
        assert launcher.launch(protected) == "busy"
    finally:
        os.close(fd)


class PhysicalDocker(FakeDocker):
    def __init__(self, directory):
        super().__init__()
        self.path = directory / physical_lock.NAME
        self.raw = environment(ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED="true")
        self.malformed = False
        self.replace = False
        self.phases = []

    def call(self, *args, **kwargs):
        if args[:2] in {("container", "create"), ("container", "start")}:
            assert not exclusive(self.path)
            self.phases.append(args[1])
        if args[:2] == ("container", "create"):
            self.calls.append((args, kwargs))
            assert os.pread(kwargs["fd"], 16384, 0) == self.raw
            info = self.path.stat()
            assert (
                "type=bind,src="
                + str(self.path)
                + ",dst="
                + physical_lock.WORKER_PATH
                + ",readonly"
                in args
            )
            assert "--env=ACCOUNT_MAIL_PHYSICAL_DEVICE=" + str(info.st_dev) in args
            assert "--env=ACCOUNT_MAIL_PHYSICAL_INODE=" + str(info.st_ino) in args
            if self.replace:
                self.path.rename(self.path.with_name("retired-inode"))
                self.path.touch(mode=0o600)
            return IDENT
        if args[:2] == ("container", "inspect"):
            return json.dumps(
                [
                    {
                        "Type": "bind",
                        "Source": str(self.path),
                        "Destination": physical_lock.WORKER_PATH,
                        "RW": self.malformed,
                    }
                ]
            )
        return super().call(*args, **kwargs)

    def lock_mounted(self, ident, claim):
        return docker_worker.Docker.lock_mounted(self, ident, claim)

    def clean(self, nonce, ident):
        # A replaced path intentionally points elsewhere; the descriptor remains
        # claimed and replacement is rejected before any child can start.
        if not self.replace:
            assert not exclusive(self.path)
        self.phases.append("cleanup")
        return super().clean(nonce, ident)


def test_launcher_holds_shared_claim_before_create_through_attached_child_and_cleanup(
    protected, monkeypatch
):
    fake = PhysicalDocker(protected)
    install_fake(monkeypatch, fake)
    assert launcher.launch(protected) == "idle"
    assert fake.phases == ["create", "start", "cleanup"]
    assert exclusive(fake.path)


@pytest.mark.parametrize(
    "fault",
    ["writable_mount", "replaced_inode", "worker_timeout", "cleanup_unconfirmed"],
)
def test_ambiguous_mount_identity_child_or_cleanup_never_reports_success(
    protected, monkeypatch, fault
):
    fake = PhysicalDocker(protected)
    fake.malformed = fault == "writable_mount"
    fake.replace = fault == "replaced_inode"
    fake.failure = fault == "worker_timeout"
    fake.clean_ok = fault != "cleanup_unconfirmed"
    install_fake(monkeypatch, fake)
    with pytest.raises(launcher.Unavailable):
        launcher.launch(protected)
    if fault in {"writable_mount", "replaced_inode"}:
        assert "start" not in fake.phases
    assert "cleanup" in fake.phases


def test_replaced_name_cannot_retarget_an_already_open_shared_claim(protected):
    path = protected / physical_lock.NAME
    with physical_lock.shared(protected) as claim:
        path.rename(protected / "old-lock")
        path.touch(mode=0o600)
        with pytest.raises(launcher.Unavailable, match="mail_physical_lock_replaced"):
            claim.verify()
        assert not exclusive(protected / "old-lock")


def test_actual_worker_claim_survives_launcher_sigkill_until_worker_process_exits(
    protected,
):
    # Each process opens its own SH descriptor. The worker does not depend on
    # the launcher's inherited fd, DB session, clock, lease, or stdout lifetime.
    child = """import os,signal,sys
from pathlib import Path
from ops.accountmail.physical_lock import shared
with shared(Path(sys.argv[1])) as claim:
 assert claim
 print(os.getpid(),flush=True)
 while True: signal.pause()
"""
    parent = """import signal,subprocess,sys
from pathlib import Path
from ops.accountmail.physical_lock import shared
with shared(Path(sys.argv[1])) as claim:
 assert claim
 process=subprocess.Popen([sys.executable,'-c',sys.argv[2],sys.argv[1]],stdout=subprocess.PIPE,text=True)
 print(process.stdout.readline().strip(),flush=True)
 while True: signal.pause()
"""
    source = Path(launcher.__file__).resolve().parents[2]
    process = subprocess.Popen(
        [sys.executable, "-c", parent, str(protected), child],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=source,
        env={**os.environ, "PYTHONPATH": str(source)},
    )
    worker = None
    try:
        assert select.select([process.stdout], [], [], 5)[0]
        worker = int(process.stdout.readline())
        assert worker > 1 and not exclusive(protected / physical_lock.NAME)
        process.kill()
        process.wait(timeout=3)
        assert not exclusive(protected / physical_lock.NAME)
        os.kill(worker, signal.SIGKILL)
        until = time.monotonic() + 3
        while time.monotonic() < until and not exclusive(
            protected / physical_lock.NAME
        ):
            time.sleep(0.01)
        assert exclusive(protected / physical_lock.NAME)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=3)
        if worker is not None:
            try:
                os.kill(worker, signal.SIGKILL)
            except ProcessLookupError:
                pass
