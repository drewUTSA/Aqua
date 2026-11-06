"""Private operator-container peer; stdout is a bounded control/binary protocol.

The host controller must verify code/image, actual maintenance and exact mounts
before starting this process. It never receives an application DB credential.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import struct
import sys

DIRECTORY = Path("/run/aqua-retirement-backup")
PUBLIC_FIELDS = frozenset(
    {
        "schemaVersion",
        "installation_id",
        "identity_key_id",
        "key_commitment",
        "public_key",
        "runtime_image",
        "source_sha256",
    }
)
RECOVERY_DSN = re.compile(
    r"postgresql://aqua_retirement_recovery:[A-Za-z0-9_-]{43}@/aqua_retirement\?host=/run/aqua-app-db&port=5432&sslmode=disable\Z"
)


def public_profile() -> dict:
    from retirement.settings import private_bytes
    from retirement.fingerprints import canonical_uuid

    if not os.statvfs(DIRECTORY).f_flag & os.ST_RDONLY:
        raise RuntimeError("retirement_export_inputs_not_readonly")

    def pairs(items):
        result = {}
        for name, value in items:
            if name in result:
                raise ValueError("retirement_export_duplicate_field")
            result[name] = value
        return result

    value = json.loads(
        private_bytes(DIRECTORY / "verification.json", 4096), object_pairs_hook=pairs
    )
    if (
        type(value) is not dict
        or set(value) != PUBLIC_FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or any(
            type(value[name]) is not str for name in PUBLIC_FIELDS - {"schemaVersion"}
        )
    ):
        raise RuntimeError("retirement_export_verification_profile_invalid")
    canonical_uuid(value["installation_id"])
    canonical_uuid(value["identity_key_id"])
    if any(
        not re.fullmatch(r"[a-f0-9]{64}", value[name])
        for name in ("key_commitment", "public_key", "source_sha256")
    ) or not re.fullmatch(r"sha256:[a-f0-9]{64}", value["runtime_image"]):
        raise RuntimeError("retirement_export_verification_profile_invalid")
    return value


def protected(value):
    from retirement.checkpoint import ProtectedFile

    return ProtectedFile(
        DIRECTORY / "checkpoints.bin",
        owner_uid=1000,
        public_key=bytes.fromhex(value["public_key"]),
        installation=value["installation_id"],
        key_id=value["identity_key_id"],
        commitment=bytes.fromhex(value["key_commitment"]),
    )


def head(value: dict) -> dict:
    """No key or database credential is mounted/read for this public projection."""
    checkpoint = protected(value)
    last = checkpoint.head(full=True)
    fd, before = checkpoint._open()
    try:
        digest = hashlib.sha256()
        remaining = before.st_size
        while remaining:
            raw = os.read(fd, min(65536, remaining))
            if not raw:
                raise RuntimeError("retirement_export_checkpoint_truncated")
            digest.update(raw)
            remaining -= len(raw)
        raw = os.pread(fd, 208, before.st_size - 208)
        checkpoint._unchanged(fd, before)
    finally:
        os.close(fd)
    return {
        **value,
        "protected_chain_sha256": digest.hexdigest(),
        "head_hex": raw.hex(),
        "sequence": last.sequence,
        "event_digest": last.event_digest.hex(),
        "total_host_restore_supported": False,
    }


def dump_bridge() -> bytes:
    """The host runs a separate SELECT-only dump role while our gate stays held."""
    from ops.retirement.archive import MAX_DUMP

    sys.stdout.buffer.write(b"AUTHORITY_DUMP\n")
    sys.stdout.buffer.flush()
    size = sys.stdin.buffer.read(8)
    if len(size) != 8:
        raise RuntimeError("retirement_export_dump_frame_missing")
    count = struct.unpack("!Q", size)[0]
    if not 5 < count <= MAX_DUMP:
        raise RuntimeError("retirement_export_dump_frame_capacity")
    data = bytearray()
    while len(data) < count:
        chunk = sys.stdin.buffer.read(min(65536, count - len(data)))
        if not chunk:
            raise RuntimeError("retirement_export_dump_frame_truncated")
        data.extend(chunk)
    return bytes(data)


def export(value: dict) -> None:
    """Only a complete current head and original manifests can produce a bundle."""
    import psycopg
    from retirement.settings import private_bytes
    from ops.retirement.archive import MAX_ARCHIVE, write
    from ops.retirement.backup_protocol import capture

    if any(name.startswith("PG") for name in os.environ):
        raise RuntimeError("retirement_export_ambient_database_configuration")
    dsn = private_bytes(DIRECTORY / "recovery.dsn", 512).decode()
    if not RECOVERY_DSN.fullmatch(dsn):
        raise RuntimeError("retirement_export_recovery_role_invalid")
    identity = private_bytes(DIRECTORY / "identity.key", 32, exact=32)
    signing = private_bytes(DIRECTORY / "signing.key", 32, exact=32)
    with psycopg.connect(
        dsn, autocommit=True, prepare_threshold=None, connect_timeout=2
    ) as conn:
        conn.execute("SET statement_timeout='3s'")
        conn.execute("SET lock_timeout='1s'")
        conn.execute("SET idle_in_transaction_session_timeout='10s'")
        bundle = capture(
            conn,
            protected(value),
            identity,
            signing,
            dump=dump_bridge,
            runtime_image=value["runtime_image"],
            source_sha256=value["source_sha256"],
        )
    output = io.BytesIO()
    write(bundle, output)
    raw = output.getvalue()
    if not 0 < len(raw) <= MAX_ARCHIVE:
        raise RuntimeError("retirement_export_archive_capacity")
    sys.stdout.buffer.write(b"ARCHIVE " + str(len(raw)).encode() + b"\n")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("head", "export"))
    arguments = parser.parse_args()
    if arguments.action is None:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "pool_opens": 0,
                    "writes": 0,
                    "total_host_restore_supported": False,
                },
                sort_keys=True,
            )
        )
        return
    value = public_profile()
    if arguments.action == "head":
        print(json.dumps(head(value), sort_keys=True))
    else:
        export(value)


if __name__ == "__main__":
    main()
