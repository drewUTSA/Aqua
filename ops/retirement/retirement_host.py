"""Private host-only bounded publisher adapter. No production activation.

Default invocation prints a plan without reading config/key files or opening a
pool. Execute only in the reviewed host publisher container: network-none,
UID1000, bounded resources, checkpoint-dir RW, HOST-dir RO, code/socket RO.
Backend receives checkpoint-dir RO and never receives host config/signing key.
"""

from dataclasses import dataclass, field
import hmac
import json
import math
import os
from pathlib import Path
import re
import signal
import stat
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

_source = Path(__file__).resolve()
_backend = _source.parents[2] / "backend"
sys.path.insert(
    0, str(_backend if _backend.is_dir() else _source.parent.parent / "backend-sources")
)
from retirement.checkpoint import ProtectedFile  # noqa: E402
from retirement.fingerprints import canonical_uuid  # noqa: E402
from retirement.publisher import HostPublisher  # noqa: E402

CHECKPOINT_DIRECTORY = Path("/run/aqua-retirement")
HOST_DIRECTORY = Path("/run/aqua-retirement-host")
MAX_SECONDS = 55
MAX_STEPS = 55
CADENCE = 1.0
FIELDS = frozenset(
    {
        "installation_id",
        "identity_key_id",
        "key_commitment",
        "public_key",
        "checkpoint_dsn",
    }
)
DSN = re.compile(
    r"postgresql://aqua_retirement_checkpoint:[A-Za-z0-9_-]{43}@/aqua_retirement\?host=/run/aqua-app-db&port=5432&sslmode=disable\Z"
)


class HostUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("retirement_publisher_unavailable")


@dataclass(frozen=True)
class HostSettings:
    installation: str
    key_id: str
    commitment: bytes
    public_key: bytes
    dsn: str = field(repr=False)


def _pairs(items):
    result = {}
    for name, value in items:
        if name in result:
            raise HostUnavailable()
        result[name] = value
    return result


def parse_settings(raw):
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= 4096:
            raise HostUnavailable()
        values = json.loads(raw, object_pairs_hook=_pairs)
        if (
            type(values) is not dict
            or set(values) != FIELDS
            or any(type(value) is not str for value in values.values())
            or not DSN.fullmatch(values["checkpoint_dsn"])
            or any(
                not re.fullmatch("[a-f0-9]{64}", values[name])
                for name in ("key_commitment", "public_key")
            )
        ):
            raise HostUnavailable()
        canonical_uuid(values["installation_id"])
        canonical_uuid(values["identity_key_id"])
        return HostSettings(
            values["installation_id"],
            values["identity_key_id"],
            bytes.fromhex(values["key_commitment"]),
            bytes.fromhex(values["public_key"]),
            values["checkpoint_dsn"],
        )
    except (ValueError, TypeError, UnicodeError):
        raise HostUnavailable() from None


def read_private(path, limit, *, exact=None):
    """Mode/UID/link/size/FD/path checks precede bounded allocation."""
    fd = None
    try:
        if (
            os.name != "posix"
            or os.geteuid() != 1000
            or not path.is_absolute()
            or path.resolve(strict=True) != path
        ):
            raise HostUnavailable()
        directory = path.parent.lstat()
        if (
            not stat.S_ISDIR(directory.st_mode)
            or directory.st_uid != 1000
            or stat.S_IMODE(directory.st_mode) != 0o700
        ):
            raise HostUnavailable()
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
        before = os.fstat(fd)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_uid != 1000
            or before.st_nlink != 1
            or stat.S_IMODE(before.st_mode) != 0o600
            or not 0 < before.st_size <= limit
            or exact is not None
            and before.st_size != exact
        ):
            raise HostUnavailable()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        after, named = os.fstat(fd), path.lstat()
        if (
            len(raw) != before.st_size
            or (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_nlink,
                after.st_uid,
                stat.S_IMODE(after.st_mode),
            )
            != (before.st_dev, before.st_ino, before.st_size, 1, 1000, 0o600)
            or (named.st_dev, named.st_ino, named.st_size)
            != (before.st_dev, before.st_ino, before.st_size)
            or path.resolve(strict=True) != path
        ):
            raise HostUnavailable()
        return raw
    except (OSError, ValueError):
        raise HostUnavailable() from None
    finally:
        if fd is not None:
            os.close(fd)


def signing_key(path, public_key):
    raw = read_private(path, 32, exact=32)
    key = Ed25519PrivateKey.from_private_bytes(raw)
    if not hmac.compare_digest(
        key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw), public_key
    ):
        raise HostUnavailable()
    return key


def readonly_backend_checkpoint(path):
    """Readiness prerequisite for backend-only mount; publisher uses RW."""
    if os.name != "posix" or not os.statvfs(path).f_flag & os.ST_RDONLY:
        raise HostUnavailable()
    return True


def pool_for(settings):
    # Fail on ambient libpq configuration rather than changing unrelated
    # analytical connections or silently accepting a service/host substitution.
    if type(settings) is not HostSettings or any(
        name.startswith("PG") for name in os.environ
    ):
        raise HostUnavailable()
    from psycopg_pool import ConnectionPool

    def configure(conn):
        if not conn.autocommit or conn.info.transaction_status != 0:
            raise HostUnavailable()
        conn.execute("SET statement_timeout='3s'")
        conn.execute("SET lock_timeout='1s'")
        conn.execute("SET idle_in_transaction_session_timeout='10s'")
        conn.execute("SET timezone='UTC'")
        row = conn.execute(
            "SELECT current_database(),current_user,session_user,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if row != (
            "aqua_retirement",
            "aqua_retirement_checkpoint",
            "aqua_retirement_checkpoint",
            False,
            False,
            False,
            False,
            False,
            False,
            1,
        ):
            raise HostUnavailable()
        if conn.execute(
            "SELECT has_database_privilege(current_user,current_database(),'TEMP'),has_schema_privilege(current_user,'retirement','CREATE'),pg_has_role(current_user,'aqua_retirement_owner','MEMBER'),has_table_privilege(current_user,'retirement.intents','INSERT,UPDATE,DELETE,TRUNCATE')"
        ).fetchone() != (False, False, False, False):
            raise HostUnavailable()
        for name in ("fsync", "full_page_writes", "synchronous_commit"):
            if conn.execute("SHOW " + name).fetchone() != ("on",):
                raise HostUnavailable()
        row = conn.execute(
            "SELECT installation_id,identity_key_id,key_commitment FROM retirement.identity_context()"
        ).fetchone()
        if (
            type(row) is not tuple
            or len(row) != 3
            or str(row[0]) != settings.installation
            or str(row[1]) != settings.key_id
            or row[2] != settings.commitment
        ):
            raise HostUnavailable()

    def reset(conn):
        try:
            if not conn.autocommit or conn.info.transaction_status != 0:
                raise HostUnavailable()
            conn.execute("DISCARD ALL")
        except Exception:
            raise HostUnavailable() from None

    return ConnectionPool(
        settings.dsn,
        min_size=0,
        max_size=1,
        max_waiting=1,
        num_workers=1,
        timeout=1,
        reconnect_timeout=3,
        max_lifetime=300,
        max_idle=30,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 2},
        configure=configure,
        reset=reset,
        check=ConnectionPool.check_connection,
        name="aqua-retirement-publisher",
    )


def tick_loop(publisher, *, deadline, clock=time.monotonic, sleep=time.sleep):
    """No source flag bypasses this55-step/1s cadence bound."""
    if (
        type(deadline) not in (int, float)
        or not math.isfinite(deadline)
        or deadline > clock() + MAX_SECONDS
        or deadline <= clock()
    ):
        raise HostUnavailable()
    steps, last = 0, None
    while steps < MAX_STEPS and clock() < deadline:
        began = clock()
        last = publisher.once()
        steps += 1
        remaining = deadline - clock()
        if remaining <= 0:
            break
        delay = min(max(0, CADENCE - (clock() - began)), remaining)
        if delay:
            sleep(delay)
    return {"status": "checked" if last is not None else "idle", "steps": steps}


def execute(*, deadline=None):
    now = time.monotonic()
    if deadline is None:
        deadline = now + MAX_SECONDS
    if (
        type(deadline) not in (int, float)
        or not math.isfinite(deadline)
        or not 0 < deadline - now <= MAX_SECONDS
    ):
        raise HostUnavailable()
    pool = None
    previous = signal.signal(
        signal.SIGALRM, lambda *args: (_ for _ in ()).throw(HostUnavailable())
    )
    # Start the hard timer before any config/key/pool I/O. The launcher supplies
    # an earlier deadline, leaving room for pool close and owned Docker cleanup.
    signal.setitimer(signal.ITIMER_REAL, deadline - now)
    try:
        settings = parse_settings(read_private(HOST_DIRECTORY / "host.json", 4096))
        key = signing_key(HOST_DIRECTORY / "signing.key", settings.public_key)
        protected = ProtectedFile(
            CHECKPOINT_DIRECTORY / "checkpoints.bin",
            owner_uid=1000,
            public_key=settings.public_key,
            installation=settings.installation,
            key_id=settings.key_id,
            commitment=settings.commitment,
        )
        pool = pool_for(settings)
        pool.open(wait=False)
        publisher = HostPublisher(pool, protected, key)
        publisher.startup()
        return tick_loop(publisher, deadline=deadline)
    finally:
        try:
            if pool is not None:
                # The hard timer remains active through connection/thread drain.
                pool.close(timeout=1)
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "key_reads": 0,
                    "pool_opens": 0,
                    "max_seconds": MAX_SECONDS,
                    "max_steps": MAX_STEPS,
                }
            )
        )
    elif sys.argv[1:] == ["--execute"] or (
        len(sys.argv) == 4 and sys.argv[1:3] == ["--execute", "--deadline"]
    ):
        try:
            outcome = execute(
                deadline=float(sys.argv[3]) if len(sys.argv) == 4 else None
            )
        except BaseException:
            print(json.dumps({"status": "unavailable"}))
            raise SystemExit(1) from None
        print(json.dumps(outcome))
    else:
        raise SystemExit(2)
