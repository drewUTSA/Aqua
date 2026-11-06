"""Bounded actual native129 original-manifest archive producer; no live inputs.

A successful explicit run writes framed public receipt + synthetic archive only
after exact owned cleanup. No plaintext archive/dump/key is saved to host disk.
"""

import argparse
import hashlib
import io
import json
import os
import signal
import re
from pathlib import Path
import sys
import time

import p05_browser_docker as commands
import run_backend
from retirement_capture_resources import CaptureResources
from retirement_host_resources import BASE, IMAGE, RUN
from retirement_host_setup import database, directories, flag, running, states
from retirement_host_protocol import role, start
from retirement_host_cancel import Cancellation


class WorkAlarm:
    def __init__(self, cancellation):
        self.cancellation = cancellation

    def __enter__(self):
        self.previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self.cancellation.receive)
        signal.alarm(180)

    def __exit__(self, *args):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.previous)


ROOT = Path(__file__).resolve().parents[2]
MAX_ARCHIVE = 193 * 1024 * 1024
DUMP_PROGRAM = "IFS= read -r PGPASSWORD || exit 1; export PGPASSWORD; exec pg_dump -h /run/aqua-app-db -p 5432 -U aqua_retirement_backup -d aqua_retirement -Fc --schema=retirement --no-owner --no-privileges"


def source():
    run_backend.ROOT = ROOT
    return run_backend.source_archive()


def full_dump(resources, password, report):
    database_id = resources.inspect("pg")
    if database_id is None or database_id != resources.created.get("pg"):
        raise RuntimeError("capture_owned_database_identity_changed")
    value = commands.docker(
        "exec",
        "-i",
        database_id,
        "/bin/sh",
        "-c",
        DUMP_PROGRAM,
        data=password.encode() + b"\n",
        timeout=30,
    )
    if not 5 < len(value) <= 128 * 1024 * 1024 or not value.startswith(b"PGDMP"):
        raise RuntimeError("capture_full_dump_invalid")
    report["dump_sha256"] = hashlib.sha256(value).hexdigest()
    report["dump_bytes"] = len(value)
    return value


def cleanup(resources, processes, report, before, cancel):
    cancel.cleaning = True
    resources.cleanup_until = time.monotonic() + 60
    remaining = []
    swept = list(resources.attempted)
    for item in reversed(swept):
        try:
            if not resources.remove(item):
                remaining.append(item)
        except Exception:
            remaining.append(item)
    for process in processes:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    cleared = False
    if not remaining and all(
        (resources.root / "authority" / item).exists()
        for item in ("checkpoints.bin", "poison.bin")
    ):
        try:
            flag(resources, "clear")
            cleared = True
            for item in ("checkpoints.bin", "poison.bin"):
                (resources.root / "authority" / item).unlink()
            (resources.root / "authority").rmdir()
        except Exception:
            remaining.append("append_flag_cleanup")
    for item in reversed(resources.attempted):
        if item in swept:
            continue
        try:
            if not resources.remove(item):
                remaining.append(item)
        except Exception:
            remaining.append(item)
    if resources.volume_attempted:
        try:
            if not resources.remove_socket():
                remaining.append("socket_volume")
        except Exception:
            remaining.append("socket_volume")
    report.update(
        append_flags_cleared=cleared,
        append_flags_never_set="set" not in resources.attempted,
        remaining_resources=remaining,
    )
    report["cleanup"] = not remaining and (cleared or report["append_flags_never_set"])
    try:
        report["existing_running_containers_unchanged"] = (
            states([item[0] for item in before]) == before
        )
    except Exception:
        report["existing_running_containers_unchanged"] = False


def execute(image, expected, name):
    if (
        not IMAGE.fullmatch(image)
        or not RUN.fullmatch(name)
        or os.geteuid() != 1000
        or sys.platform != "linux"
        or BASE.resolve(strict=True) != BASE
    ):
        raise RuntimeError("capture_exact_owned_linux_scope_required")
    raw = source()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("capture_source_changed")
    sys.path[:0] = [
        str(ROOT),
        str(ROOT / "backend"),
        str(ROOT / "tools/checks/retirement_fixture"),
    ]
    from ops.retirement.export_protocol import Channel, archive
    from retirement.checkpoint import ProtectedFile
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from retirement.fingerprints import IdentityKey
    from native_support import AUTH_PASSWORD, IDENTITY_BYTES, INSTALLATION, KEY_ID, SEED

    # Prove the native host interpreter supports the needed signature codec
    # before its first Docker command, using only the public fixture seed.
    fixture_key = Ed25519PrivateKey.from_private_bytes(SEED)
    fixture_public = fixture_key.public_key().public_bytes(
        Encoding.Raw, PublicFormat.Raw
    )
    fixture_key.public_key().verify(
        fixture_key.sign(b"capture-host-preflight"), b"capture-host-preflight"
    )

    if (
        commands.docker(
            "image", "inspect", image, "--format={{.Id}}", timeout=10
        ).strip()
        != image.encode()
    ):
        raise RuntimeError("capture_image_changed")
    resources = CaptureResources(
        name,
        image,
        (ROOT / "tools/checks/retirement_fixture/append_flags.py").read_bytes(),
        expected,
    )
    before = running()
    directories(resources, raw)
    report = {
        "run": name,
        "source_sha256": expected,
        "image_id": image,
        "status": "failed",
        "cleanup": False,
        "production_mutations": 0,
        "private_inputs_read": False,
        "original_manifest_count": 129,
        "original_page_sizes": [128, 1],
        "http_origin_129_claimed": False,
        "total_host_restore_supported": False,
    }
    processes = []
    log = bytearray()
    output = io.BytesIO()
    bundle = None
    with Cancellation() as cancellation, WorkAlarm(cancellation):
        try:
            database(resources, ROOT)
            initialized = role(resources, "initialize", processes, log)
            resources.initialized(initialized)
            flag(resources, "set")
            role(resources, "publish0", processes, log)
            process = start(resources, "capture", processes)
            channel = Channel(process, time.monotonic() + 100)
            if channel.line() != b"CAPTURE129_PUBLISH":
                raise RuntimeError("capture_publication_stage_invalid")
            role(resources, "publish1", processes, log)
            # Read/verify the actual retained inode independently in the host,
            # after the separate signer has exited. It is never supplied by the
            # archive's own profile as its expected head.
            key = IdentityKey(KEY_ID, IDENTITY_BYTES)
            protected = ProtectedFile(
                resources.root / "authority/checkpoints.bin",
                owner_uid=1000,
                public_key=fixture_public,
                installation=INSTALLATION,
                key_id=KEY_ID,
                commitment=key.commitment,
            )
            head = protected.head(full=True)
            if head.sequence != 1:
                raise RuntimeError("capture_external_head_not_sequence_one")
            fd, meta = protected._open()
            try:
                chain = os.read(fd, meta.st_size + 1)
                protected._unchanged(fd, meta)
            finally:
                os.close(fd)
            report.update(
                protected_head_hex=chain[-208:].hex(),
                protected_chain_sha256=hashlib.sha256(chain).hexdigest(),
                event_digest=head.event_digest.hex(),
                sequence=head.sequence,
                installation_id=INSTALLATION,
                identity_key_id=KEY_ID,
                key_commitment=key.commitment.hex(),
                public_key=protected.public_key.hex(),
                checkpoint_device=meta.st_dev,
                checkpoint_inode=meta.st_ino,
            )
            channel.write(b"continue\n")

            def dump():
                return full_dump(resources, AUTH_PASSWORD, report)

            first = channel.line()
            if first != b"AUTHORITY_DUMP":
                match = re.fullmatch(
                    rb"CAPTURE129_ERROR ([A-Za-z_][A-Za-z0-9_]{0,31}):([a-z0-9_]{1,64})",
                    first,
                )
                if match:
                    report["producer_failure_class"] = match[1].decode()
                    report["producer_failure_category"] = match[2].decode()
                else:
                    report["unexpected_protocol_line_sha256"] = hashlib.sha256(
                        first
                    ).hexdigest()
                raise RuntimeError("capture_producer_failed_before_dump_request")
            channel.pending = bytearray(first + b"\n") + channel.pending
            transfer = archive(channel, dump, output)
            if not resources.remove("capture"):
                raise RuntimeError("capture_producer_exit_unconfirmed")
            bundle = output.getvalue()
            if len(bundle) > MAX_ARCHIVE:
                raise RuntimeError("capture_archive_capacity")
            report.update(
                status="passed",
                archive_sha256=transfer["plaintext_sha256"],
                archive_bytes=len(bundle),
                capture_gate="actual_cap1_recovery_role_through_full_backup_role_dump",
                compiled_runtime=True,
            )
        except (Exception, KeyboardInterrupt) as error:
            report["error"] = type(error).__name__ + ":" + str(error)[:160]
        finally:
            signal.alarm(0)
            cleanup(resources, processes, report, before, cancellation)
            if (
                not report["cleanup"]
                or not report["existing_running_containers_unchanged"]
            ):
                report["status"] = "failed"
            (resources.root / "report.json").write_text(
                json.dumps(report, indent=2) + "\n"
            )
            (resources.root / "cases.log").write_bytes(log)
    if report["status"] != "passed":
        bundle = None
    return report, bundle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image", default="")
    parser.add_argument("--source-sha256", default="")
    parser.add_argument("--run", default="")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "prepared_only", "Docker_actions": 0, "writes": 0}))
        return 0
    report, bundle = execute(args.image, args.source_sha256, args.run)
    header = json.dumps(report, sort_keys=True, separators=(",", ":")).encode()
    sys.stdout.buffer.write(b"RECEIPT " + str(len(header)).encode() + b"\n" + header)
    if bundle is not None:
        sys.stdout.buffer.write(
            b"ARCHIVE " + str(len(bundle)).encode() + b"\n" + bundle
        )
    sys.stdout.buffer.flush()
    return int(bundle is None)


if __name__ == "__main__":
    raise SystemExit(main())
