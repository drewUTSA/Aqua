"""Prepare or execute only a fresh native two-DB/inode/mail-lifetime rehearsal."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

import p05_browser_docker as commands
from retirement_host_resources import BASE, IMAGE, RUN, Resources
from retirement_host_protocol import lines, mail, role, send, start
from retirement_host_setup import database, directories, flag, running, states
from retirement_host_cancel import Cancellation
import run_backend

ROOT = Path(__file__).resolve().parents[2]


def source() -> bytes:
    run_backend.ROOT = ROOT
    return run_backend.source_archive()


def _execute(image: str, expected: str, name: str, cancellation) -> int:
    if (
        not IMAGE.fullmatch(image)
        or not RUN.fullmatch(name)
        or os.geteuid() != 1000
        or sys.platform != "linux"
        or BASE.resolve(strict=True) != BASE
    ):
        raise RuntimeError("native_fixture_exact_linux_scope_required")
    raw = source()
    digest = hashlib.sha256(raw).hexdigest()
    if expected != digest:
        raise RuntimeError("native_fixture_source_changed_after_review")
    sys.path[:0] = [
        str(ROOT),
        str(ROOT / "backend"),
        str(ROOT / "tools/checks/retirement_fixture"),
    ]
    if (
        commands.docker(
            "image", "inspect", image, "--format={{.Id}}", timeout=10
        ).strip()
        != image.encode()
    ):
        raise RuntimeError("native_fixture_dependency_image_pin_mismatch")
    resources = Resources(
        name,
        image,
        (ROOT / "tools/checks/retirement_fixture/append_flags.py").read_bytes(),
    )
    before = running()
    directories(resources, raw)
    report = {
        "run": name,
        "source_sha256": digest,
        "image_id": image,
        "production_mutations": 0,
        "private_inputs_read": False,
        "cleanup": False,
        "total_host_restore_claimed": False,
    }
    processes = []
    log = bytearray()
    dump = None
    publishes = 0
    try:
        database(resources, ROOT)
        initialized = role(resources, "initialize", processes, log)
        if initialized.get("status") != "initialized":
            raise RuntimeError("native_fixture_initializer_failed")
        report["initializer"] = initialized
        resources.initialized(initialized)
        flag(resources, "set")
        report["provisioning_sequence"] = [
            "initializer_removed_and_absence_confirmed",
            "append_set_readback_and_setter_exit",
            "new_api_and_signer_created_after_flag",
        ]
        api = start(resources, "api", processes)
        for line in lines(api, time.monotonic() + 110, log):
            if line == b"READY_FOR_BACKUP":
                dump = commands.docker(
                    "exec",
                    name + "-pg",
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-d",
                    "aqua_app",
                    "--format=custom",
                    timeout=15,
                )
                if len(dump) > 8 * 1024 * 1024 or not dump.startswith(b"PGDMP"):
                    raise RuntimeError("native_fixture_synthetic_dump_capacity")
                report["synthetic_app_dump_sha256"] = hashlib.sha256(dump).hexdigest()
                send(api, "continue")
            elif line == b"READY_FOR_RESTORE":
                if dump is None:
                    raise RuntimeError("native_fixture_synthetic_dump_missing")
                commands.docker(
                    "exec",
                    "-i",
                    name + "-pg",
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
                    name + "-pg",
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
                send(api, "continue")
            elif line == b"NATIVE_PUBLISH":
                value = role(resources, "publish" + str(publishes), processes, log)
                publishes += 1
                if value.get("status") != "published":
                    raise RuntimeError("native_fixture_publisher_failed")
                send(api, "continue")
            elif line == b"NATIVE_CRASH_BEFORE_ACK":
                report["preACK_failure"] = role(resources, "crash", processes, log)
                send(api, "continue")
            elif line == b"NATIVE_POISON":
                report["poison"] = role(resources, "poison", processes, log)
                send(api, "continue")
            elif line.startswith(b"{"):
                report["composition"] = json.loads(line)
        if (
            api.wait(timeout=5) != 0
            or report.get("composition", {}).get("status") != "passed"
            or not resources.remove("api")
        ):
            raise RuntimeError("native_fixture_API_composition_or_exit_failed")
        if not report["composition"].get(
            "append_only_inode_storage_proven"
        ) or not report["composition"].get("physical_mail_mount_proven"):
            raise RuntimeError("native_fixture_mocked_storage_not_acceptable")
        report["physical_mail"] = mail(resources, ROOT, processes, log)
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        report["status"] = "failed"
        report["error"] = type(error).__name__ + ":" + str(error)[:180]
    finally:
        cancellation.cleaning = True
        resources.cleanup_until = time.monotonic() + 60
        dump = None
        remaining = []
        swept = list(resources.attempted)
        for item in reversed(swept):
            try:
                if not resources.remove(item):
                    remaining.append(item)
            except Exception:
                remaining.append(item)
        # Removing actual containers precedes killing local Docker clients.
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
        # Clearing flags can create a privileged container after the first
        # sweep. Retry only these newly registered owned names if its own
        # finally cleanup was interrupted or a daemon response was lost.
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
        report["append_flags_cleared"] = cleared
        never_set = "set" not in resources.attempted
        report["append_flags_never_set"] = never_set
        report["remaining_resources"] = remaining
        report["cleanup"] = not remaining and (cleared or never_set)
        try:
            report["existing_running_containers_unchanged"] = (
                states([item[0] for item in before]) == before
            )
        except Exception:
            report["existing_running_containers_unchanged"] = False
        (resources.root / "cases.log").write_bytes(log)
        (resources.root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"directory": str(resources.root), **report}, sort_keys=True))
    return int(
        report.get("status") != "passed"
        or not report["cleanup"]
        or not report["existing_running_containers_unchanged"]
    )


def execute(image: str, expected: str, name: str) -> int:
    with Cancellation() as cancellation:
        return _execute(image, expected, name, cancellation)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image", default="")
    parser.add_argument("--source-sha256", default="")
    parser.add_argument("--run", default="")
    arguments = parser.parse_args()
    if not arguments.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "Docker_actions": 0,
                    "writes": 0,
                    "source_sha256": hashlib.sha256(source()).hexdigest(),
                    "private_inputs": False,
                    "requires_native_Linux_UID": 1000,
                    "review_before_execution": True,
                },
                sort_keys=True,
            )
        )
        return 0
    return execute(arguments.image, arguments.source_sha256, arguments.run)


if __name__ == "__main__":
    raise SystemExit(main())
