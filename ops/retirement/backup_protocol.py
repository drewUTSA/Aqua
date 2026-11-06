"""Offline operator archival transaction; no ambient paths, keys or services.

The caller must supply a bounded dump bridge and an encrypted-output controller.
Only a retained authority gate plus a complete sealed head can be captured.
"""

import hashlib
import os
from typing import Callable

from retirement.checkpoint import RECORD_BYTES
from retirement.interlock import LOCK, NAMESPACE

if __package__:
    from .archive import Bundle, MAX_DUMP, checked
    from .operator_deadline import deadline
else:
    from archive import Bundle, MAX_DUMP, checked
    from operator_deadline import deadline


def _capture(
    conn,
    protected,
    identity: bytes,
    signing: bytes,
    *,
    dump: Callable[[], bytes],
    runtime_image: str,
    source_sha256: str,
) -> Bundle:
    """Hold one physical authority session gate through the independent dump.

    The dump uses the separate SELECT-only archival role's single slot. The
    recovery-role gate uses its own single slot, never a second backup connection.
    All normal writers/publisher must already be stopped by the host controller;
    this gate also blocks protocol writers during the bounded capture itself.
    """
    if not conn.autocommit or conn.info.transaction_status != 0:
        raise RuntimeError("retirement_backup_connection_not_idle")
    row = conn.execute(
        "SELECT current_database(),current_user,session_user,rolsuper,rolinherit,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls,rolconnlimit FROM pg_roles WHERE rolname=current_user"
    ).fetchone()
    if row != (
        "aqua_retirement",
        "aqua_retirement_recovery",
        "aqua_retirement_recovery",
        False,
        False,
        False,
        False,
        False,
        False,
        1,
    ):
        raise RuntimeError("retirement_backup_gate_role_invalid")
    if conn.execute("SHOW default_transaction_read_only").fetchone() != ("on",):
        raise RuntimeError("retirement_backup_gate_not_readonly")
    for name in ("fsync", "full_page_writes", "synchronous_commit"):
        if conn.execute("SHOW " + name).fetchone() != ("on",):
            raise RuntimeError("retirement_backup_durability_disabled")
    if conn.execute(
        "SELECT pg_try_advisory_lock(%s,%s)", (NAMESPACE, LOCK)
    ).fetchone() != (True,):
        raise RuntimeError("retirement_backup_gate_unavailable")
    try:
        head = protected.require_current(conn, allow_pending=False, full=True)
        # Actual signed-chain bytes are read only after the verifier caps and
        # validates their inode. The common gate prevents a concurrent append.
        fd, before = protected._open()
        try:
            parts = []
            remaining = before.st_size
            while remaining:
                raw = os.read(fd, min(remaining, 65536))
                if not raw:
                    raise RuntimeError("retirement_backup_chain_truncated")
                parts.append(raw)
                remaining -= len(raw)
            protected._unchanged(fd, before)
        finally:
            os.close(fd)
        chain = b"".join(parts)
        raw_dump = dump()
        if (
            type(raw_dump) is not bytes
            or not raw_dump.startswith(b"PGDMP")
            or not len(raw_dump) <= MAX_DUMP
        ):
            raise RuntimeError("retirement_backup_dump_invalid")
        if protected.require_current(conn, allow_pending=False) != head:
            raise RuntimeError("retirement_backup_head_changed")
        contents = {
            "authority.dump": raw_dump,
            "checkpoints.bin": chain,
            "identity.key": identity,
            "signing.key": signing,
        }
        profile = {
            "schemaVersion": 1,
            "installation_id": head.installation,
            "identity_key_id": head.key_id,
            "key_commitment": head.key_commitment.hex(),
            "public_key": protected.public_key.hex(),
            "runtime_image": runtime_image,
            "source_sha256": source_sha256,
            "files": {
                name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()
            },
        }
        return checked(contents, profile, chain[-RECORD_BYTES:])
    finally:
        # A failed unlock poisons this operator connection. It cannot be pooled
        # or silently reused while a former gate might still be held.
        try:
            if conn.execute(
                "SELECT pg_advisory_unlock(%s,%s)", (NAMESPACE, LOCK)
            ).fetchone() != (True,):
                raise RuntimeError("retirement_backup_unlock_failed")
            if conn.execute(
                "SELECT count(*) FROM pg_locks WHERE pid=pg_backend_pid() AND locktype='advisory'"
            ).fetchone() != (0,):
                raise RuntimeError("retirement_backup_gate_leaked")
        except Exception:
            conn.close()
            raise RuntimeError("retirement_backup_gate_cleanup_unconfirmed") from None


def capture(
    conn,
    protected,
    identity: bytes,
    signing: bytes,
    *,
    dump: Callable[[], bytes],
    runtime_image: str,
    source_sha256: str,
) -> Bundle:
    """One120-second operator process; never a periodic-backup readiness claim."""
    with deadline():
        return _capture(
            conn,
            protected,
            identity,
            signing,
            dump=dump,
            runtime_image=runtime_image,
            source_sha256=source_sha256,
        )
