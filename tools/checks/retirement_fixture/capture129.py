"""Fresh synthetic account129 producer for actual operator capture/SQL restore.

Only an owned native fixture may run it. No HTTP-origin claim: this explicit
manifest tests the actual independent protocol's128+1 page archival closure.
"""

import argparse
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import re
import signal
import struct
import sys
from uuid import uuid4

from native_support import AUTH_PASSWORD, IDENTITY_BYTES, INSTALLATION, KEY_ID, SEED


def original():
    from retirement.fingerprints import IdentityKey, ISSUER
    from retirement.intents import Intent
    from retirement.pages import encode, manifest

    key = IdentityKey(KEY_ID, IDENTITY_BYTES)
    data = manifest(
        encode("d" * 64, key.google(ISSUER, f"archive129-synthetic-{index:03}"))
        for index in range(129)
    )
    if data.count != 129 or tuple(map(len, data.pages)) != (128, 1):
        raise RuntimeError("capture129_explicit_original_manifest_invalid")
    record = Intent(
        INSTALLATION,
        str(uuid4()),
        str(uuid4()),
        str(uuid4()),
        "account_v1",
        datetime.now(timezone.utc),
        2,
        2,
        1,
        True,
        fingerprint_count=data.count,
        fingerprint_root=data.root,
    )
    return key, record, data


def dump_bridge() -> bytes:
    from ops.retirement.archive import MAX_DUMP

    sys.stdout.buffer.write(b"AUTHORITY_DUMP\n")
    sys.stdout.buffer.flush()
    size = sys.stdin.buffer.read(8)
    if len(size) != 8:
        raise RuntimeError("capture129_dump_frame_missing")
    length = struct.unpack("!Q", size)[0]
    if not 5 < length <= MAX_DUMP:
        raise RuntimeError("capture129_dump_capacity")
    result = bytearray()
    while len(result) < length:
        value = sys.stdin.buffer.read(min(65536, length - len(result)))
        if not value:
            raise RuntimeError("capture129_dump_truncated")
        result.extend(value)
    return bytes(result)


def capture_phase(capture, *args, **kwargs):
    # The preparation process timer cannot be nested inside the production
    # operator deadline. Preparation/seal+writer exit are complete here; the
    # host's original absolute100s channel still bounds the whole producer.
    signal.alarm(0)
    return capture(*args, **kwargs)


def failure(error):
    name = type(error).__name__
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", name):
        name = "Exception"
    code = str(error)
    if not re.fullmatch(r"(?:retirement_|capture129_)[a-z0-9_]{1,48}", code):
        state = getattr(error, "sqlstate", None)
        code = (
            "sqlstate_" + state.lower()
            if type(state) is str and re.fullmatch(r"[A-Z0-9]{5}", state)
            else "unclassified"
        )
    return "CAPTURE129_ERROR " + name + ":" + code


def execute(run: str, image: str, source: str) -> None:
    if (
        sys.platform != "linux"
        or os.geteuid() != 1000
        or os.environ.get("AQUA_RETIREMENT_NATIVE_FIXTURE") != "true"
        or not re.fullmatch(r"aqua-retirement-host-[a-f0-9]{24}", run)
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)
        or not re.fullmatch(r"[a-f0-9]{64}", source)
    ):
        raise RuntimeError("capture129_owned_native_scope_required")
    import psycopg
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from psycopg_pool import ConnectionPool
    from retirement.checkpoint import ProtectedFile
    from retirement.client import (
        AuthorityClient,
        ConfirmedAcceptance,
        ConfirmedRetirement,
    )
    from retirement.interlock import Broker
    from retirement.pages import INITIAL, page_digest
    from ops.retirement.backup_protocol import capture
    from ops.retirement.archive import MAX_ARCHIVE, write

    directory = Path("/run/aqua-retirement")
    if not os.statvfs(directory).f_flag & os.ST_RDONLY:
        raise RuntimeError("capture129_readonly_protected_mount_required")
    key, record, data = original()
    protected = ProtectedFile(
        directory / "checkpoints.bin",
        owner_uid=1000,
        public_key=Ed25519PrivateKey.from_private_bytes(SEED)
        .public_key()
        .public_bytes_raw(),
        installation=INSTALLATION,
        key_id=KEY_ID,
        commitment=key.commitment,
    )

    def role(name):
        return f"host=/run/aqua-app-db port=5432 dbname=aqua_retirement user=aqua_retirement_{name} password={AUTH_PASSWORD} sslmode=disable"

    pool = ConnectionPool(
        role("writer"),
        min_size=0,
        max_size=1,
        num_workers=1,
        timeout=1,
        kwargs={"autocommit": True, "prepare_threshold": None, "connect_timeout": 2},
    )
    try:
        authority = AuthorityClient(
            Broker(pool, INSTALLATION, key=key, checkpoint=protected)
        )
        if authority.startup_checkpoint().sequence != 0:
            raise RuntimeError("capture129_requires_fresh_genesis_only")
        authority.prepare(record, data)
        print("CAPTURE129_PUBLISH", flush=True)
        if sys.stdin.buffer.readline() != b"continue\n":
            raise RuntimeError("capture129_publisher_controller_missing")
        accepted = authority.confirm_acceptance(
            record.owner, record.intent, record.scope
        )
        if (
            type(accepted) is not ConfirmedAcceptance
            or accepted.checkpoint_sequence != 1
        ):
            raise RuntimeError("capture129_actual_signed_ACK_missing")
        previous = INITIAL
        for ordinal, page in enumerate(data.pages):
            authority.append_page(record.intent, ordinal, previous, page)
            previous = page_digest(previous, ordinal, page)
        authority.seal(record.intent)
        if (
            type(authority.confirm(record.owner, record.intent, record.scope))
            is not ConfirmedRetirement
        ):
            raise RuntimeError("capture129_complete_seal_missing")
    finally:
        pool.close(timeout=3)
    # Independent recovery gate and SELECT-only backup dump occupy two slots;
    # writer/checkpoint pools have actually exited. No slot/cap is broadened.
    with psycopg.connect(role("recovery"), autocommit=True, connect_timeout=2) as conn:
        bundle = capture_phase(
            capture,
            conn,
            protected,
            IDENTITY_BYTES,
            SEED,
            dump=dump_bridge,
            runtime_image=image,
            source_sha256=source,
        )
    output = io.BytesIO()
    write(bundle, output)
    raw = output.getvalue()
    if len(raw) > MAX_ARCHIVE:
        raise RuntimeError("capture129_archive_capacity")
    sys.stdout.buffer.write(b"ARCHIVE " + str(len(raw)).encode() + b"\n")
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run", default="")
    parser.add_argument("--image", default="")
    parser.add_argument("--source-sha256", default="")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "pool_opens": 0,
                    "writes": 0,
                }
            )
        )
        return
    signal.alarm(100)
    try:
        execute(args.run, args.image, args.source_sha256)
    except Exception as error:
        print(failure(error), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
