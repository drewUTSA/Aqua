"""Real OS file locks retain actual sender lifetime after its parent/DB exits."""

import os
import signal

import pytest

from retirement import mail_physical
from retirement.interlock import RetirementUnavailable


@pytest.mark.parametrize("flag", (None, "false"))
def test_installed_authority_requires_actual_host_claim_even_when_worker_flag_missing_or_false(
    storage, monkeypatch, flag
):
    from auth.mailconfig import MailPolicy
    from auth.mailqueue import MailOutbox
    from auth.mailworker import MailWorker
    from storage.pool import StorageUnavailable

    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.retirement_control SET authority_installed=true WHERE singleton"
        )
    if flag is None:
        monkeypatch.delenv(mail_physical.FLAG, raising=False)
    else:
        monkeypatch.setenv(mail_physical.FLAG, flag)
    box = MailOutbox(storage, MailPolicy(True, b"k" * 32, "https://mail.fixture"))
    calls = []
    transport = type(
        "FakeTransport", (), {"send": lambda self, *args: calls.append(args)}
    )()
    with pytest.raises(StorageUnavailable, match="physical_unavailable"):
        MailWorker(box, transport).once()
    with pytest.raises(StorageUnavailable, match="physical_unavailable"):
        box.claim()
    with pytest.raises(StorageUnavailable, match="physical_unavailable"):
        with box.physical(True):
            pytest.fail("a boolean forged a host descriptor claim")
    assert calls == []
    with storage.transaction() as conn:
        assert conn.execute(
            "SELECT lease_id FROM app.account_mail_control"
        ).fetchone() == (None,)


def test_installed_authority_host_claim_is_checked_on_same_single_slot_before_real_fake_transport(
    storage, monkeypatch, tmp_path
):
    from auth.mailconfig import MailPolicy
    from auth.mailoutbox import enqueue
    from auth.mailqueue import MailOutbox
    from auth.mailworker import MailWorker

    policy = MailPolicy(True, b"k" * 32, "https://mail.fixture")
    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.retirement_control SET authority_installed=true WHERE singleton"
        )
        expiry = conn.execute(
            "SELECT clock_timestamp()+interval '60 seconds'"
        ).fetchone()[0]
        enqueue(
            conn,
            recipient="fake-physical@example.invalid",
            purpose="password_changed",
            token=None,
            expires_at=expiry,
            policy=policy,
        )
    path = tmp_path / "worker.lock"
    path.touch(mode=0o600)
    monkeypatch.setattr(
        mail_physical, "_open", lambda selected: os.open(path, os.O_RDONLY)
    )
    monkeypatch.setattr(mail_physical, "WORKER_PATH", path)
    monkeypatch.setenv(mail_physical.FLAG, "true")
    monkeypatch.setenv(mail_physical.DEVICE, str(path.stat().st_dev))
    monkeypatch.setenv(mail_physical.INODE, str(path.stat().st_ino))
    box = MailOutbox(storage, policy)
    calls = []

    class FakeTransport:
        def send(self, job_id, payload):
            assert box._connection.info.transaction_status == 0
            mail_physical.require_claim(box._host_claim)
            calls.append(job_id)
            return "accepted"

    assert MailWorker(box, FakeTransport()).once() is True
    assert len(calls) == 1
    assert storage._pool.get_stats()["pool_size"] == 1
    with storage.transaction() as conn:
        assert conn.execute("SELECT state FROM app.account_mail").fetchone() == (
            "sent",
        )


def test_installed_marker_cannot_be_unset_and_missing_authority_never_opens_backend(
    storage,
):
    from retirement.runtime import Runtime
    from storage.pool import StorageUnavailable

    with storage.transaction() as conn:
        conn.execute(
            "UPDATE app.retirement_control SET authority_installed=true WHERE singleton"
        )
    with pytest.raises(StorageUnavailable):
        with storage.transaction() as conn:
            conn.execute(
                "UPDATE app.retirement_control SET authority_installed=false WHERE singleton"
            )
    runtime = Runtime(storage)
    with pytest.raises(RetirementUnavailable):
        runtime.start()
    assert runtime.ready is False


def test_installed_runtime_rejects_unprotected_or_writable_mail_lifetime_file(tmp_path):
    private = tmp_path / "physical"
    private.mkdir(mode=0o700)
    path = private / "worker.lock"
    path.touch(mode=0o600)
    with pytest.raises(RetirementUnavailable):
        mail_physical._open(path)
    path.unlink()
    path.symlink_to(tmp_path / "missing")
    with pytest.raises(RetirementUnavailable):
        mail_physical._open(path)


@pytest.mark.skipif(not hasattr(os, "fork"), reason="POSIX flock lifetime")
def test_actual_worker_descriptor_blocks_cleanup_until_real_process_exit(
    tmp_path, monkeypatch
):
    import fcntl

    path = tmp_path / "worker.lock"
    path.touch(mode=0o600)
    read, write = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(read)
        fd = os.open(path, os.O_RDONLY)
        fcntl.flock(fd, fcntl.LOCK_SH)
        os.write(write, b"1")
        os.close(write)
        while True:
            signal.pause()
    os.close(write)
    try:
        assert os.read(read, 1) == b"1"
        # This seam bypasses provisioning only. The conflict is the real OS
        # cross-process flock, not a fake clock, SQL lease or Python registry.
        monkeypatch.setattr(
            mail_physical, "_open", lambda selected: os.open(path, os.O_RDONLY)
        )
        monkeypatch.setattr(mail_physical, "WEB_PATH", path)
        monkeypatch.setattr(mail_physical, "WORKER_PATH", path)
        current = path.stat()
        monkeypatch.setenv(mail_physical.DEVICE, str(current.st_dev))
        monkeypatch.setenv(mail_physical.INODE, str(current.st_ino))
        with mail_physical.gate() as acquired:
            assert acquired is False
        # A dead DB/launcher cannot close the sender process's descriptor.
        with mail_physical.gate(worker=True) as acquired:
            mail_physical.require_claim(acquired)
        with pytest.raises(RetirementUnavailable):
            mail_physical.require_claim(acquired)
    finally:
        os.close(read)
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
    with mail_physical.gate() as acquired:
        assert acquired is True
