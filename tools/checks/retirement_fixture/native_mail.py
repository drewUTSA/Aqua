"""Real MailWorker and OS descriptor lifetime, with a blocking fake provider."""

import json
import os
from pathlib import Path
import re
import signal
import sys

from ops.accountmail.physical_lock import shared

SCOPE = re.compile(r"aqua-retirement-host-[a-f0-9]{24}\Z")


def receive(expected: str) -> None:
    if sys.stdin.readline().strip() != expected:
        raise RuntimeError("native_mail_controller_missing")


def launcher(directory: Path, run: str) -> None:
    """Use the production host SH API in the same Linux kernel as Docker."""
    if directory != Path("/srv/bank-ai/.check-results") / run / "mail":
        raise RuntimeError("native_mail_host_path_scope_invalid")
    with shared(directory) as claim:
        if claim is None:
            raise RuntimeError("native_mail_launcher_busy")
        print(
            json.dumps(
                {
                    "event": "launcher_locked",
                    "device": claim.device,
                    "inode": claim.inode,
                }
            ),
            flush=True,
        )
        receive("never_sent_before_SIGKILL")


def web() -> None:
    from retirement import mail_physical

    with mail_physical.gate() as acquired:
        current = mail_physical.WEB_PATH.lstat()
        print(
            json.dumps(
                {
                    "acquired": acquired,
                    "device": current.st_dev,
                    "inode": current.st_ino,
                }
            ),
            flush=True,
        )


def worker(run: str) -> None:
    """The actual outbox/claim/decrypt/transport/finish path owns one DB slot."""
    from auth.mailconfig import MailPolicy
    from auth.mailoutbox import enqueue
    from auth.mailqueue import MailOutbox
    from auth.mailworker import MailWorker
    from retirement import mail_physical
    from retirement.interlock import RetirementUnavailable
    from storage.config import StorageSettings
    from storage.pool import Storage, StorageUnavailable

    settings = StorageSettings(
        True,
        "host=/run/aqua-app-db port=5432 dbname=aqua_app user=aqua_app_runtime password=fixture-only sslmode=disable",
        1,
        1,
        1,
    )
    storage = Storage(settings)
    policy = MailPolicy(True, b"k" * 32, "https://mail.fixture")
    outbox = MailOutbox(storage, policy)
    saved, calls = [], []
    try:
        with storage.transaction() as conn:
            expiry = conn.execute(
                "SELECT clock_timestamp()+interval '90 seconds'"
            ).fetchone()[0]
            enqueue(
                conn,
                recipient="native-synthetic@example.invalid",
                purpose="password_changed",
                token=None,
                expires_at=expiry,
                policy=policy,
            )

        class FakeTransport:
            def send(self, job, payload):
                assert not calls
                calls.append(job)
                conn = outbox._connection
                assert conn.info.transaction_status == 0
                conn.execute(
                    "SELECT set_config('application_name',%s,false)", (run + "-mail",)
                )
                claim = outbox._host_claim
                mail_physical.require_claim(claim)
                saved.append(claim)
                current = os.fstat(claim.descriptor)
                print(
                    json.dumps(
                        {
                            "event": "mail_sending",
                            "pid": conn.info.backend_pid,
                            "application_name": run + "-mail",
                            "device": current.st_dev,
                            "inode": current.st_ino,
                            "actual_MailWorker": True,
                        }
                    ),
                    flush=True,
                )
                receive("verify_after_DB_death")
                mail_physical.require_claim(claim)
                print(json.dumps({"event": "claim_survives_DB_death"}), flush=True)
                receive("verify_after_launcher_death")
                mail_physical.require_claim(claim)
                print(
                    json.dumps({"event": "claim_survives_launcher_death"}), flush=True
                )
                receive("finish_fake_send")
                return "accepted"

        try:
            MailWorker(outbox, FakeTransport()).once()
        except StorageUnavailable:
            assert len(calls) == 1
        else:
            raise AssertionError("terminated_mail_backend_committed_finish")
        try:
            mail_physical.require_claim(saved[0])
        except RetirementUnavailable:
            pass
        else:
            raise AssertionError("expired_mail_host_claim_reused")
        print(
            json.dumps(
                {
                    "status": "expected_DB_loss_after_one_fake_send",
                    "old_host_claim_rejected": True,
                    "fake_send_calls": 1,
                    "app_pool_max": storage.settings.max_connections,
                }
            ),
            flush=True,
        )
    finally:
        storage.close()


def main() -> None:
    if len(sys.argv) not in {3, 4} or not SCOPE.fullmatch(sys.argv[2]):
        raise RuntimeError("native_mail_scope_invalid")
    role, run = sys.argv[1:3]
    signal.alarm(40)
    if role == "launcher" and len(sys.argv) == 4:
        launcher(Path(sys.argv[3]), run)
    elif role == "worker" and len(sys.argv) == 3:
        worker(run)
    elif role == "web" and len(sys.argv) == 3:
        web()
    else:
        raise RuntimeError("native_mail_role_invalid")


if __name__ == "__main__":
    main()
