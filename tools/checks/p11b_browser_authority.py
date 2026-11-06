"""Actual isolated two-DB retirement; only ioctl/mail-mount are named seams."""

from contextlib import nullcontext
import hashlib
import hmac
import os
from pathlib import Path
from collections.abc import Callable
from typing import Any

INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
MATERIAL = b"synthetic-fixture-HMAC-key-only!".ljust(32, b"0")
ROLES = (
    "aqua_retirement_writer",
    "aqua_retirement_checkpoint",
    "aqua_retirement_recovery",
)


def dsn(role: str) -> str:
    if role not in ROLES:
        raise ValueError("fixture_authority_role_denied")
    return (
        "host=/run/aqua-app-db port=5432 dbname=aqua_retirement user="
        + role
        + " password=fixture-only sslmode=disable"
    )


def provision(docker: Callable, pg: str, root: Path) -> None:
    """Existing run-owned PG only; no extra container, port or provider."""
    prefix = b"\\set writer_password 'fixture-only'\n\\set recovery_password 'fixture-only'\n\\set checkpoint_password 'fixture-only'\n"
    docker(
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        data=prefix + (root / "ops/retirement/bootstrap.psql").read_bytes(),
    )
    commitment = hmac.new(
        MATERIAL, b"AQUA:retirement-key-check:v1\0", hashlib.sha256
    ).hexdigest()
    prefix = (
        "\\set installation_id '"
        + INSTALLATION
        + "'\n\\set identity_key_id '"
        + KEY_ID
        + "'\n\\set key_commitment '"
        + commitment
        + "'\n"
    ).encode()
    docker(
        "exec",
        "-i",
        pg,
        "psql",
        "-X",
        "-v",
        "ON_ERROR_STOP=1",
        "-U",
        "postgres",
        data=prefix + (root / "ops/retirement/schema.psql").read_bytes(),
    )
    hba = b"local all postgres peer\n"
    for role in ("aqua_app_runtime", "aqua_app_migrator"):
        hba += ("local aqua_app " + role + " scram-sha-256\n").encode()
    for role in ROLES:
        hba += ("local aqua_retirement " + role + " scram-sha-256\n").encode()
    hba += b"local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
    docker("exec", "-i", pg, "tee", "/var/lib/postgresql/data/pg_hba.conf", data=hba)
    docker("exec", pg, "psql", "-X", "-U", "postgres", "-c", "SELECT pg_reload_conf()")


class Authority:
    def __init__(self, storage: Any, settings: Any) -> None:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from psycopg_pool import ConnectionPool
        from auth.config import load_auth_policy
        from privacy.deletion_service import Deletions
        from privacy.deletion_worker import Worker
        from retirement import checkpoint
        from retirement.client import AuthorityClient
        from retirement.fingerprints import IdentityKey
        from retirement.interlock import Broker
        from retirement.publisher import HostPublisher, signed_record
        from retirement.runtime import Runtime
        from retirement import mail_physical

        self.storage, self.publishes, self.ticks = storage, 0, 0
        self.writer = ConnectionPool(
            dsn(ROLES[0]),
            min_size=0,
            max_size=1,
            max_waiting=1,
            timeout=1,
            kwargs={
                "autocommit": True,
                "prepare_threshold": None,
                "connect_timeout": 2,
            },
        )
        self.host = ConnectionPool(
            dsn(ROLES[1]),
            min_size=0,
            max_size=1,
            max_waiting=1,
            timeout=1,
            kwargs={
                "autocommit": True,
                "prepare_threshold": None,
                "connect_timeout": 2,
            },
        )
        self.previous_ioctl = checkpoint.append_only
        checkpoint.append_only = (
            lambda fd: True
        )  # Explicit unsupported tmpfs ioctl seam.
        self.previous_mail_validate = mail_physical.validate
        mail_physical.validate = lambda: None  # Explicit absent production mount seam.
        directory = Path("/tmp/p11b-browser-authority")
        directory.mkdir(mode=0o700)
        key = IdentityKey(KEY_ID, MATERIAL)
        private = Ed25519PrivateKey.generate()
        path = directory / "checkpoints.bin"
        genesis = signed_record(
            private,
            installation=INSTALLATION,
            key_id=KEY_ID,
            sequence=0,
            digest=bytes(32),
            previous=bytes(32),
            commitment=key.commitment,
        )
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            if os.write(fd, genesis) != 208:
                raise ValueError("fixture_genesis_write_failed")
            os.fsync(fd)
        finally:
            os.close(fd)
        protected = checkpoint.ProtectedFile(
            path,
            owner_uid=1000,
            public_key=private.public_key().public_bytes_raw(),
            installation=INSTALLATION,
            key_id=KEY_ID,
            commitment=key.commitment,
        )
        self.publisher = HostPublisher(self.host, protected, private)
        self.publisher.startup()
        self.publisher.once()
        self.client = AuthorityClient(
            Broker(self.writer, INSTALLATION, key=key, checkpoint=protected)
        )

        class BrowserRuntime(Runtime):
            def purge_guard(runtime, closed):
                # No sender runs in this Google-only fixture. Production's
                # independently mounted physical mail lock has separate proofs.
                return nullcontext(True)

        class ManualDeletions(Deletions):
            def start(service):
                pass  # Bounded explicit real Worker.once controls, not a fake worker.

        self.runtime = BrowserRuntime(storage, client=self.client, enabled=True)
        self.runtime.start()
        storage.retirement = self.runtime
        self.service = ManualDeletions(
            storage, load_auth_policy(settings), settings, self.runtime
        )
        self.worker = Worker(self.service)
        original = self.client.prepare

        def prepare(record, fingerprints):
            result = original(record, fingerprints)
            if record.scope == "account_v1":
                self.publish()
            return result

        self.client.prepare = prepare

    def publish(self) -> None:
        if self.publishes >= 8:
            raise ValueError("fixture_publisher_bound")
        self.publishes += 1
        self.publisher.once()

    def purge(self) -> None:
        from retirement.interlock import RetirementUnavailable

        for _ in range(24):
            if self.ticks >= 96:
                raise ValueError("fixture_purge_bound")
            self.ticks += 1
            try:
                if not self.worker.once():
                    break
            except RetirementUnavailable:
                break

    def close(self) -> None:
        from retirement import checkpoint
        from retirement import mail_physical

        self.service.close()
        self.runtime.close()
        self.writer.close(timeout=3)
        self.host.close(timeout=3)
        checkpoint.append_only = self.previous_ioctl
        mail_physical.validate = self.previous_mail_validate
