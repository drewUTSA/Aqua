"""One-shot source enrollment inside the offline, network-isolated publisher helper."""

import hashlib
import hmac
import os
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from retirement.checkpoint import ProtectedFile, RECORD_BYTES
from retirement.interlock import LOCK, NAMESPACE
from retirement.publisher import witness_sender


def write_new_or_match(path, data, read, write):
    if path.exists() or path.is_symlink():
        if not hmac.compare_digest(read(path, max(len(data), 1)), data):
            raise ValueError("forward_installation_existing_file_changed")
    else:
        write(path, data)


def operate(mode, expected, host, files):
    """The host controller holds the real maintenance gate for the entire call."""
    if not callable(getattr(host, "witness_profile_pin", None)):
        raise ValueError("forward_installed_publisher_requires_witness_support")
    source = Path("/run/aqua-forward-input")
    forward = Path("/run/aqua-forward-output")
    protected_dir = Path("/run/aqua-forward-authority")
    if (
        os.geteuid() != 1000
        or not all(
            os.statvfs(path).f_flag & os.ST_RDONLY
            for path in (source / "host.json", source / "publisher.json", protected_dir)
        )
        or os.statvfs(forward).f_flag & os.ST_RDONLY
    ):
        raise ValueError("forward_mount_boundary")
    files.directory(forward)
    original = files.read(source / "host.json", 4096)
    settings = host.parse_settings(original)
    if settings.witness is not None or (
        settings.installation,
        settings.key_id,
        settings.commitment.hex(),
        settings.public_key.hex(),
    ) != tuple(
        expected[k]
        for k in ("installation_id", "identity_key_id", "key_commitment", "public_key")
    ):
        raise ValueError("forward_original_installation_changed")
    profile = files.pinned(source / "publisher.json", expected["legacy_profile_sha256"])
    if (
        set(profile)
        != {
            "schemaVersion",
            "runtime_image",
            "source_sha256",
            "code_manifest_sha256",
            "host_code_manifest_sha256",
        }
        or type(profile.get("schemaVersion")) is not int
        or profile["schemaVersion"] != 1
        or (
            profile["runtime_image"],
            profile["source_sha256"],
        )
        != (expected["runtime_image"], expected["source_sha256"])
    ):
        raise ValueError("forward_original_profile_changed")
    station = Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(expected["witness_public_key"])
    )
    if station.public_bytes_raw() == settings.public_key:
        raise ValueError("forward_witness_must_be_separate")
    protected = ProtectedFile(
        protected_dir / "checkpoints.bin",
        owner_uid=1000,
        public_key=settings.public_key,
        installation=settings.installation,
        key_id=settings.key_id,
        commitment=settings.commitment,
    )
    with (
        host.pool_for(settings) as pool,
        pool.connection(timeout=2) as conn,
        conn.transaction(),
    ):
        if conn.execute(
            "SELECT pg_try_advisory_xact_lock(%s,%s)", (NAMESPACE, LOCK)
        ).fetchone() != (True,):
            raise ValueError("forward_authority_busy")
        current = protected.require_current(conn, full=True)
        if (
            current.sequence != 0
            or current.record_digest.hex() != expected["genesis_sha256"]
        ):
            raise ValueError(
                "forward_only_requires_independently_identified_fresh_genesis"
            )
        fd, meta = protected._open()
        try:
            genesis = os.read(fd, RECORD_BYTES + 1)
            protected._unchanged(fd, meta)
        finally:
            os.close(fd)
        if (
            len(genesis) != RECORD_BYTES
            or hashlib.sha256(genesis).digest() != current.record_digest
        ):
            raise ValueError("forward_genesis_changed")
        if mode == "inspect":
            return {
                "status": "fresh_genesis_verified",
                "genesis_sha256": current.record_digest.hex(),
            }
        keypath = forward / "publication.key"
        if mode == "prepare":
            if any(forward.iterdir()):
                raise ValueError("forward_directory_already_used")
            private = Ed25519PrivateKey.generate()
            files.write_once(keypath, private.private_bytes_raw())
            public = private.public_key().public_bytes_raw()
            host.signing_key(keypath, public)
            return {
                "status": "service_key_prepared",
                "service_public_key": public.hex(),
                "signed_genesis": genesis.hex(),
            }
        if mode != "activate":
            raise ValueError("forward_operation")
        public = bytes.fromhex(expected["service_public_key"])
        private = host.signing_key(keypath, public)
        if len({public, settings.public_key, station.public_bytes_raw()}) != 3:
            raise ValueError("forward_separate_identities_required")
        receipt = witness_sender(forward / "witness.sock", 1, private, station)(genesis)
        if receipt != current.record_digest:
            raise ValueError("forward_station_confirmation")
        values = files.parse(original)
        values["witness"] = {
            "generation": 1,
            "service_public_key": public.hex(),
            "witness_public_key": station.public_bytes_raw().hex(),
        }
        new = files.json_bytes(values)
        pin = host.witness_profile_pin(host.parse_settings(new))
        publisher = files.json_bytes(
            {**profile, "schemaVersion": 2, "witness_sha256": pin}
        )
        write_new_or_match(forward / "host-v2.json", new, files.read, files.write_once)
        write_new_or_match(
            forward / "publisher-v2.json", publisher, files.read, files.write_once
        )
        return {
            "status": "witness_verified_writers_still_stopped",
            "witness_sha256": pin,
            "publisher_profile_sha256": hashlib.sha256(publisher).hexdigest(),
            "genesis_sha256": receipt.hex(),
        }
