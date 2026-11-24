"""Exercise the installed forward operator using only the new native QA installation."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
import socket
import subprocess
import sys
from uuid import uuid4


def check(fixture, head, receipt):
    from ops.retirement.operator_files import json_bytes, read, write_once
    from prepare_retirement_stage import checked_archive, full_source

    fixture.scope.validate()
    if not fixture.scope.qa_run or fixture.root != fixture.scope.parent:
        raise RuntimeError("forward_native_fixture_required")
    cache = checked_archive(full_source(fixture.source_root), fixture.source_sha256)
    for name in ("forward_controller.py", "forward_source.py"):
        write_once(fixture.stage / name, cache["ops/recovery_witness/" + name])
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    sys.path.insert(0, str(fixture.source_root / "backend"))
    from ops.recovery_witness.journal import Identity, Witness
    from ops.recovery_witness.station import serve_connection

    station = Ed25519PrivateKey.generate()
    station_public = station.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    raw = bytes.fromhex(head["head_hex"])
    digest = hashlib.sha256(raw).hexdigest()
    fields = ("installation_id", "identity_key_id", "key_commitment", "public_key")
    envelope = {key: head[key] for key in (*fields, "runtime_image", "source_sha256")}
    envelope.update(
        genesis_sha256=digest,
        witness_public_key=station_public.hex(),
        plan_sha256=hashlib.sha256(read(fixture.scope.plan)).hexdigest(),
        legacy_profile_sha256=receipt["publisher_profile_sha256"],
        helper_sha256=hashlib.sha256(
            cache["ops/recovery_witness/forward_source.py"]
        ).hexdigest(),
    )
    target = fixture.scope.private / "host/forward-v1"

    def write_envelope(mode):
        encoded = json_bytes(envelope)
        write_once(
            fixture.scope.private / "operator" / ("forward-" + mode + ".json"), encoded
        )
        return hashlib.sha256(encoded).hexdigest()

    def invoke(mode, pin, *, denied=False):
        result = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                "-B",
                str(fixture.stage / "forward_controller.py"),
                mode,
                "--qa-run",
                fixture.run,
                "--execute",
                "--envelope-sha256",
                pin,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=60,
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"},
        )
        if result.returncode != int(denied) or len(result.stdout) > 4096:
            raise RuntimeError("forward_rehearsal_" + mode + "_cli")
        outcome = json.loads(result.stdout)
        if denied and outcome != {
            "status": "forward_enrollment_unavailable",
            "writers_resumed": False,
        }:
            raise RuntimeError("forward_rehearsal_expected_denial")
        return outcome

    pin = write_envelope("prepare")
    invoke("prepare", "0" * 64, denied=True)
    if target.exists():
        raise RuntimeError("forward_rehearsal_unexpected_preparation")
    prepared = invoke("prepare", pin)
    if (
        prepared.get("status") != "service_key_prepared"
        or prepared["signed_genesis"] != raw.hex()
    ):
        raise RuntimeError("forward_rehearsal_genesis")
    invoke("prepare", pin, denied=True)
    service = bytes.fromhex(prepared["service_public_key"])
    envelope["service_public_key"] = service.hex()
    pin = write_envelope("activate")
    invoke("activate", pin, denied=True)
    if (target / "host-v2.json").exists() or (target / "publisher-v2.json").exists():
        raise RuntimeError("forward_rehearsal_unverified_profile_created")

    identity = Identity(
        head[fields[0]],
        head[fields[1]],
        bytes.fromhex(head[fields[2]]),
        bytes.fromhex(head[fields[3]]),
    )
    witness = Witness(fixture.root / "fixture-witness.sqlite3", identity)
    witness.enroll(raw, service_public_key=service)
    endpoint = target / "witness.sock"
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
        listener.bind(str(endpoint))
        inode = endpoint.lstat()
        try:
            os.chmod(endpoint, 0o600)
            listener.listen(1)
            listener.settimeout(20)

            def receive():
                connection, _ = listener.accept()
                with connection:
                    serve_connection(connection, witness, 1, service, station)

            with ThreadPoolExecutor(max_workers=1) as pool:
                for attempt in range(2):
                    work = pool.submit(receive)
                    current = invoke("activate", pin)
                    work.result(timeout=10)
                    if attempt == 0:
                        first = current
                    elif current != first:
                        raise RuntimeError("forward_rehearsal_retry_changed")
            if (
                first["status"] != "witness_verified_writers_still_stopped"
                or first["genesis_sha256"] != digest
                or hashlib.sha256(read(target / "publisher-v2.json")).hexdigest()
                != first["publisher_profile_sha256"]
            ):
                raise RuntimeError("forward_rehearsal_installed_profile")
        finally:
            observed = endpoint.lstat()
            if (observed.st_dev, observed.st_ino) == (inode.st_dev, inode.st_ino):
                endpoint.unlink()
    witness.fence(1, str(uuid4()))
    return {
        "fresh_installation": True,
        "bad_pin_denied": True,
        "duplicate_prepare_denied": True,
        "unavailable_witness_denied": True,
        "witness_authenticated": True,
        "exact_activation_retry": True,
        "new_profile_verified": True,
        "qa_station_fenced": True,
    }
