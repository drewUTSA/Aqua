"""App-only offline recovery against retained, independently protected authority.

No archive can replace authority here. Total-host authority restore is closed:
old signed data alone is not a cryptographically verified latest-head protocol.
"""

from dataclasses import asdict
import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
from typing import Callable

if __package__:
    from .operator_deadline import deadline
else:
    from operator_deadline import deadline


def _app_only(
    storage,
    conn,
    protected,
    *,
    expected_protected_sha256: str,
    purge_guard: Callable,
    batch_limit: int = 128,
) -> dict:
    """Require the exact retained signed chain before any application repair.

    The enclosing reviewed host controller must stop and prove old processes
    absent and apply the restore-session fence before invoking this adapter.
    It must retain that maintenance boundary until this result is ready.
    The function cannot install/restore the independent DB, keys or checkpoint.
    """
    import re
    from retirement.interlock import RetirementUnavailable
    from retirement.recovery import reconcile

    if not re.fullmatch(r"[a-f0-9]{64}", expected_protected_sha256):
        raise RetirementUnavailable()
    protected.head(full=True)
    fd, before = protected._open()
    try:
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            chunk = os.read(fd, min(remaining, 65536))
            if not chunk:
                raise RetirementUnavailable()
            remaining -= len(chunk)
            digest.update(chunk)
        protected._unchanged(fd, before)
    finally:
        os.close(fd)
    if not hmac.compare_digest(digest.hexdigest(), expected_protected_sha256):
        raise RetirementUnavailable()
    result = reconcile(
        storage, conn, protected, purge_guard=purge_guard, batch_limit=batch_limit
    )
    return {
        "mode": "retained_authority_app_only",
        "protected_sha256": digest.hexdigest(),
        "total_host_authority_restore_supported": False,
        **asdict(result),
    }


def app_only(
    storage,
    conn,
    protected,
    *,
    expected_protected_sha256: str,
    purge_guard: Callable,
    batch_limit: int = 128,
) -> dict:
    """Keep the exact-chain check and repair behind the same authority gate."""
    from retirement.interlock import LOCK, NAMESPACE, RetirementUnavailable

    with deadline():
        if not conn.autocommit or conn.info.transaction_status != 0:
            raise RetirementUnavailable()
        if conn.execute(
            "SELECT pg_try_advisory_lock(%s,%s)", (NAMESPACE, LOCK)
        ).fetchone() != (True,):
            raise RetirementUnavailable()
        try:
            # reconcile takes/releases its own nested session lock. This outer
            # count remains held until the exact expected chain and repair end.
            return _app_only(
                storage,
                conn,
                protected,
                expected_protected_sha256=expected_protected_sha256,
                purge_guard=purge_guard,
                batch_limit=batch_limit,
            )
        finally:
            try:
                if conn.info.transaction_status != 0 or conn.execute(
                    "SELECT pg_advisory_unlock(%s,%s)", (NAMESPACE, LOCK)
                ).fetchone() != (True,):
                    raise RetirementUnavailable()
                if conn.execute(
                    "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"
                ).fetchone() != (0,):
                    raise RetirementUnavailable()
            except Exception:
                conn.close()
                raise RetirementUnavailable() from None


def total_host(*args, **kwargs) -> None:
    """Never turn a caller boolean/backup age/self-signed old head into recency."""
    from retirement.interlock import RetirementUnavailable

    raise RetirementUnavailable()


def main() -> None:
    """No config/key/DB access until a separate reviewed host controller exists."""
    backend = Path(__file__).resolve().parents[2] / "backend"
    if backend.is_dir():
        sys.path.insert(0, str(backend))
    if sys.argv[1:]:
        total_host()
    print(
        json.dumps(
            {
                "status": "prepared_only",
                "private_reads": 0,
                "pool_opens": 0,
                "writes": 0,
                "total_host_authority_restore_supported": False,
                "execution_requires_reviewed_stopped_writer_controller": True,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
