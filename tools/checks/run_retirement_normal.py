"""Actual normal final-image startup/flagoff purge/restore-closed/recovered-ready.

Synthetic receipt/session frames stay in RAM. All PG containers, mount sources,
keys, socket and file inodes belong to one new native QA run, never production.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import signal
import sys
import time

import p05_browser_docker as commands
import run_backend
from retirement_normal_resources import NormalResources
from retirement_normal_image import IMAGE, MANIFEST_SHA256, RUNTIME_FILES
from retirement_host_resources import BASE, RUN
from retirement_host_setup import database, directories, flag, running
from retirement_host_protocol import lines, send, start
from retirement_host_cancel import Cancellation
from run_retirement_capture import cleanup

ROOT = Path(__file__).resolve().parents[2]


class WorkAlarm:
    def __init__(self, cancel):
        self.cancel = cancel

    def __enter__(self):
        self.previous = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, self.cancel.receive)
        signal.alarm(240)

    def __exit__(self, *args):
        signal.alarm(0)
        signal.signal(signal.SIGALRM, self.previous)


def source():
    run_backend.ROOT = ROOT
    return run_backend.source_archive()


def pg(resources):
    identifier = resources.inspect("pg")
    if identifier is None or identifier != resources.created.get("pg"):
        raise RuntimeError("normal_fixture_PG_identity_changed")
    return identifier


def publish(resources, name, processes, log):
    process = start(resources, name, processes)
    result = None
    barrier = False
    for line in lines(process, time.monotonic() + 25, log):
        if not line.startswith(b"{"):
            continue
        value = json.loads(line)
        if value.get("event") == "before_ACK":
            if name != "crash" or barrier:
                raise RuntimeError("normal_fixture_unexpected_ACK_barrier")
            barrier = True
            pid = value.get("pid")
            if (
                type(pid) is not int
                or not 1 < pid < 2**31
                or value.get("application_name") != resources.run
            ):
                raise RuntimeError("normal_fixture_checkpoint_PID_invalid")
            statement = f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE pid={pid} AND usename='aqua_retirement_checkpoint' AND datname='aqua_retirement' AND application_name='{resources.run}'"
            raw = commands.docker(
                "exec",
                pg(resources),
                "psql",
                "-X",
                "-U",
                "postgres",
                "-d",
                "aqua_retirement",
                "-At",
                "-c",
                statement,
                timeout=10,
            )
            if raw.strip() != b"t":
                raise RuntimeError("normal_fixture_exact_checkpoint_not_terminated")
            send(process, "backend_terminated")
        else:
            result = value
    if process.wait(timeout=5) != 0 or result is None or not resources.remove(name):
        raise RuntimeError("normal_fixture_publisher_exit_unconfirmed")
    if name == "crash" and (
        not barrier or result.get("status") != "expected_connection_death"
    ):
        raise RuntimeError("normal_fixture_preACK_death_missing")
    return result


def fixed_backend(resources):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
    from native_support import AUTH_PASSWORD, IDENTITY_BYTES, INSTALLATION, KEY_ID, SEED
    from retirement.fingerprints import IdentityKey

    common = {
        "installation_id": INSTALLATION,
        "identity_key_id": KEY_ID,
        "key_commitment": IdentityKey(KEY_ID, IDENTITY_BYTES).commitment.hex(),
        "public_key": Ed25519PrivateKey.from_private_bytes(SEED)
        .public_key()
        .public_bytes(Encoding.Raw, PublicFormat.Raw)
        .hex(),
    }
    values = {
        "backend.json": json.dumps(
            {
                **common,
                "writer_dsn": "postgresql://aqua_retirement_writer:"
                + AUTH_PASSWORD
                + "@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable",
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
        "identity.key": IDENTITY_BYTES,
    }
    for name, raw in values.items():
        path = resources.root / "backend" / name
        fd = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
        )
        try:
            os.fchmod(fd, 0o600)
            if os.write(fd, raw) != len(raw):
                raise RuntimeError("normal_fixture_partial_public_config")
            os.fsync(fd)
        finally:
            os.close(fd)


def finish(resources, role, process):
    if process.wait(timeout=5) != 0 or not resources.remove(role):
        raise RuntimeError("normal_fixture_child_exit_unconfirmed")


def probe(resources, role, request, processes, recovery=False, public_report=None):
    from ops.retirement.export_protocol import Channel
    from retirement_normal_protocol import bounded_line

    process = start(resources, role, processes)
    channel = Channel(process, time.monotonic() + (65 if recovery else 45))
    channel.write(json.dumps(request, sort_keys=True, separators=(",", ":")).encode())
    process.stdin.close()
    if recovery:
        public = json.loads(bounded_line(channel, 16384))
        header = channel.line().split(b" ")
        if (
            len(header) != 2
            or header[0] != b"NORMAL_REPAIRED"
            or not header[1].isdigit()
            or not 0 < int(header[1]) <= 65536
        ):
            raise RuntimeError("normal_fixture_recovery_frame_invalid")
        private = io.BytesIO()
        channel.exact(int(header[1]), private)
        if channel.pending or channel.receive():
            raise RuntimeError("normal_fixture_recovery_trailing")
        result = (public, json.loads(private.getvalue()))
    else:
        output = bytearray()
        while True:
            chunk = channel.receive()
            if not chunk:
                break
            output.extend(chunk)
            if len(output) > 16384:
                raise RuntimeError("normal_fixture_probe_response_capacity")
        result = json.loads(output)
        if type(result) is dict and result.get("status") == "failed":
            from normal_runtime_probe import validate_failure

            diagnostic = validate_failure(result)
            if public_report is None or role not in {
                "normal-purge",
                "normal-closed",
                "normal-ready",
            }:
                raise RuntimeError("normal_fixture_failure_role_invalid")
            public_report["probe_failure"] = {"role": role, "diagnostic": diagnostic}
            finish(resources, role, process)
            raise RuntimeError("normal_fixture_failed_probe_reported_zero")
    finish(resources, role, process)
    return result


def execute(expected, name):
    if (
        not RUN.fullmatch(name)
        or os.geteuid() != 1000
        or sys.platform != "linux"
        or BASE.resolve(strict=True) != BASE
    ):
        raise RuntimeError("normal_fixture_exact_linux_scope_required")
    raw = source()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("normal_fixture_source_changed")
    sys.path[:0] = [
        str(ROOT),
        str(ROOT / "backend"),
        str(ROOT / "tools/checks/retirement_fixture"),
    ]
    from retirement_normal_protocol import SeedChannel

    # Required host crypto modules are checked before the first Docker call.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    Ed25519PrivateKey.from_private_bytes(bytes.fromhex("33" * 32))
    if (
        commands.docker(
            "image", "inspect", IMAGE, "--format={{.Id}}", timeout=10
        ).strip()
        != IMAGE.encode()
    ):
        raise RuntimeError("normal_fixture_image_changed")
    resources = NormalResources(
        name,
        IMAGE,
        (ROOT / "tools/checks/retirement_fixture/append_flags.py").read_bytes(),
    )
    before = running()
    directories(resources, raw)
    fixed_backend(resources)
    report = {
        "status": "failed",
        "run": name,
        "source_sha256": expected,
        "image": IMAGE,
        "runtime195_manifest_sha256": MANIFEST_SHA256,
        "production_mutations": 0,
        "private_inputs_read": False,
        "normal_runtime_injected": False,
        "seed_runtime": "explicit_existing_TestClient_setup_actor",
        "normal_web_runtime": "ordinary_settings_load_Runtime_create_no_injection",
        "whole_install_controller_exercised": False,
        "total_host_restore_supported": False,
    }
    processes = []
    log = bytearray()
    dump = None
    private = None
    seed_channel = None
    with Cancellation() as cancellation, WorkAlarm(cancellation):
        try:
            database(resources, ROOT)
            initialized = publish(resources, "initialize", processes, log)
            resources.initialized(initialized)
            flag(resources, "set")
            publish(resources, "publish0", processes, log)
            seed = start(resources, "seed", processes)
            channel = seed_channel = SeedChannel(seed, time.monotonic() + 110)
            publications = 1
            while True:
                line = channel.next_line()
                if line == b"READY_FOR_BACKUP":
                    dump = commands.docker(
                        "exec",
                        pg(resources),
                        "pg_dump",
                        "-U",
                        "postgres",
                        "-d",
                        "aqua_app",
                        "--format=custom",
                        timeout=15,
                    )
                    if not 5 < len(dump) <= 8 * 1024 * 1024 or not dump.startswith(
                        b"PGDMP"
                    ):
                        raise RuntimeError("normal_fixture_app_dump_capacity")
                    channel.write(b"continue\n")
                elif line == b"NATIVE_CRASH_BEFORE_ACK":
                    publish(resources, "crash", processes, log)
                    channel.write(b"continue\n")
                elif line == b"NATIVE_PUBLISH":
                    publish(resources, "publish" + str(publications), processes, log)
                    publications += 1
                    channel.write(b"continue\n")
                elif line.startswith(b"NORMAL_RECEIPT "):
                    header = line.split(b" ")
                    if (
                        len(header) != 2
                        or not header[1].isdigit()
                        or not 0 < int(header[1]) <= 8192
                    ):
                        raise RuntimeError("normal_fixture_receipt_frame_invalid")
                    payload = io.BytesIO()
                    channel.exact(int(header[1]), payload)
                    private = json.loads(payload.getvalue())
                    break
                else:
                    channel.diagnostic(line)
            if channel.pending or channel.receive():
                raise RuntimeError("normal_fixture_seed_trailing_payload")
            finish(resources, "seed", seed)
            request = {
                "run": name,
                "mode": "receipt_purge",
                "runtime_files": RUNTIME_FILES,
                **private,
            }
            report["accepted_flag_off_purge"] = probe(
                resources, "normal-purge", request, processes, public_report=report
            )
            if report["accepted_flag_off_purge"].get("status") != "passed":
                raise RuntimeError("normal_fixture_accepted_purge_not_passed")
            # The actual accepted account and history records survive only in
            # retained independent authority; the old application dump predates both.
            commands.docker(
                "exec",
                "-i",
                pg(resources),
                "pg_restore",
                "--clean",
                "--if-exists",
                "-U",
                "postgres",
                "-d",
                "aqua_app",
                data=dump,
                timeout=15,
            )
            dump = None
            commands.docker(
                "exec",
                "-i",
                pg(resources),
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                "postgres",
                "-d",
                "aqua_app",
                data=(ROOT / "ops/appdb/restore_session_fence.sql").read_bytes(),
                timeout=15,
            )
            report["restored_closed"] = probe(
                resources,
                "normal-closed",
                {**request, "mode": "restored_closed"},
                processes,
                public_report=report,
            )
            if report["restored_closed"].get("startup_mode") != "startup_exited_closed":
                raise RuntimeError("normal_fixture_restore_admitted")
            protected_sha = hashlib.sha256(
                (resources.root / "authority/checkpoints.bin").read_bytes()
            ).hexdigest()
            recovered, ready_request = probe(
                resources,
                "normal-recover",
                {"request": request, "protected_sha256": protected_sha},
                processes,
                recovery=True,
            )
            report["offline_retained_recovery"] = recovered
            report["recovered_ready"] = probe(
                resources,
                "normal-ready",
                ready_request,
                processes,
                public_report=report,
            )
            if report["recovered_ready"].get("status") != "passed":
                raise RuntimeError("normal_fixture_recovered_start_failed")
            report["status"] = "passed"
        except (Exception, KeyboardInterrupt) as error:
            report["error"] = type(error).__name__ + ":" + str(error)[:160]
        finally:
            cancellation.cleaning = True
            signal.alarm(0)
            dump = None
            private = None
            if seed_channel is not None:
                report["seed_diagnostics"] = seed_channel.public_diagnostics()
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
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run", default="")
    parser.add_argument("--source-sha256", default="")
    args = parser.parse_args()
    if not args.execute:
        print(json.dumps({"status": "prepared_only", "Docker_actions": 0, "writes": 0}))
        return 0
    report = execute(args.source_sha256, args.run)
    print(json.dumps(report, sort_keys=True))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
