"""Owned native signer/initializer roles with no installed keys or config reads."""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops.retirement.initialize import genesis
from ops.retirement.retirement_host import parse_settings, pool_for
from retirement.checkpoint import ProtectedFile
from retirement.fingerprints import IdentityKey
from retirement.interlock import RetirementUnavailable
from retirement.publisher import HostPublisher
from native_support import AUTH_PASSWORD, IDENTITY_BYTES, INSTALLATION, KEY_ID, SEED

DIRECTORY = Path("/fixture/authority")
KEY = IdentityKey(KEY_ID, IDENTITY_BYTES)
PRIVATE = Ed25519PrivateKey.from_private_bytes(SEED)
PUBLIC = PRIVATE.public_key().public_bytes_raw()


def protected() -> ProtectedFile:
    return ProtectedFile(
        DIRECTORY / "checkpoints.bin",
        owner_uid=1000,
        public_key=PUBLIC,
        installation=INSTALLATION,
        key_id=KEY_ID,
        commitment=KEY.commitment,
    )


def initialize() -> dict:
    """Every write FD closes in this process, which must exit before APPEND."""
    receipt = genesis(
        DIRECTORY,
        SEED,
        installation=INSTALLATION,
        key_id=KEY_ID,
        commitment=KEY.commitment,
        public_key=PUBLIC,
    )
    raw = (DIRECTORY / "checkpoints.bin").read_bytes()
    fd = os.open(
        DIRECTORY / "poison.bin",
        os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC,
        0o600,
    )
    try:
        assert os.write(fd, raw) == 208
        os.fsync(fd)
    finally:
        os.close(fd)
    return {"status": "initialized", **receipt}


class BeforeAck:
    """Only a timing barrier; all SQL/crypto/fsync run against actual resources."""

    def __init__(self, conn, run: str, state: dict):
        self.conn, self.run, self.state = conn, run, state

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def execute(self, query, params=None):
        if query == "SELECT retirement.acknowledge_checkpoint(%s,%s,%s)":
            if self.state.get("barrier"):
                raise RuntimeError("native_preACK_barrier_repeated")
            self.state["barrier"] = True
            raw = protected().path.read_bytes()
            print(
                json.dumps(
                    {
                        "event": "before_ACK",
                        "pid": self.conn.info.backend_pid,
                        "application_name": self.run,
                        "checkpoint_bytes": len(raw),
                        "checkpoint_sha256": hashlib.sha256(raw).hexdigest(),
                    }
                ),
                flush=True,
            )
            if sys.stdin.readline().strip() != "backend_terminated":
                raise RuntimeError("native_preACK_controller_missing")
        return self.conn.execute(query, params)


class CrashPool:
    def __init__(self, pool, run: str):
        self.pool, self.run, self.state = pool, run, {}

    @contextmanager
    def connection(self, timeout):
        with self.pool.connection(timeout=timeout) as conn:
            conn.execute("SELECT set_config('application_name',%s,false)", (self.run,))
            yield BeforeAck(conn, self.run, self.state)


def publish(run: str, crash: bool) -> dict:
    """Use the actual strict host role pool, publisher and commit readback."""
    settings = parse_settings(
        json.dumps(
            {
                "installation_id": INSTALLATION,
                "identity_key_id": KEY_ID,
                "key_commitment": KEY.commitment.hex(),
                "public_key": PUBLIC.hex(),
                "checkpoint_dsn": "postgresql://aqua_retirement_checkpoint:"
                + AUTH_PASSWORD
                + "@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable",
            }
        ).encode()
    )
    pool = pool_for(settings)
    pool.open(wait=False)
    adapter = CrashPool(pool, run) if crash else pool
    publisher = HostPublisher(adapter, protected(), PRIVATE)
    try:
        publisher.startup()
        try:
            head = publisher.once()
        except RetirementUnavailable:
            if not crash or not adapter.state.get("barrier") or not publisher.poisoned:
                raise
            return {"status": "expected_connection_death", "poisoned": True}
        if crash:
            raise AssertionError("native_preACK_backend_death_not_observed")
        return {
            "status": "published",
            "sequence": head.sequence,
            "checkpoint_sha256": hashlib.sha256(
                protected().path.read_bytes()
            ).hexdigest(),
        }
    finally:
        pool.close(timeout=3)


def main() -> None:
    if (
        len(sys.argv) != 3
        or sys.argv[1] not in {"initialize", "publish", "crash", "poison"}
        or not re.fullmatch(r"aqua-retirement-host-[a-f0-9]{24}", sys.argv[2])
    ):
        raise RuntimeError("native_retirement_role_scope_invalid")
    signal.alarm(20)
    role, run = sys.argv[1:]
    if role == "initialize":
        result = initialize()
    elif role == "poison":
        fd = os.open(DIRECTORY / "poison.bin", os.O_WRONLY | os.O_APPEND | os.O_CLOEXEC)
        try:
            assert os.write(fd, b"x") == 1
            os.fsync(fd)
        finally:
            os.close(fd)
        result = {"status": "poisoned_fixture_tail"}
    else:
        result = publish(run, role == "crash")
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
