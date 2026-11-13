"""Run-owned socket-only current schema9 two-DB deletion composition."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import selectors
import subprocess
import sys
import time

import p05_browser_docker as commands
import p05_browser_resources as resources
import run_backend

ROOT = Path(__file__).resolve().parents[2]
DOCKER = "docker"


def docker(*args, data=None, timeout=60):
    result = subprocess.run(
        [DOCKER, *args], input=data, capture_output=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-1500:])
    return result.stdout


def owned(kind, name, run):
    if (kind, name) not in {
        ("container", run + "-pg"),
        ("container", run + "-api"),
        ("volume", run + "-socket"),
    }:
        raise RuntimeError("wrong_cleanup_scope")
    result = subprocess.run(
        [DOCKER, kind, "inspect", name], capture_output=True, timeout=10
    )
    if result.returncode:
        if "No such" in result.stderr.decode(
            errors="replace"
        ) or "no such" in result.stderr.decode(errors="replace"):
            return None
        raise RuntimeError("absence_unconfirmed")
    metadata = json.loads(result.stdout)[0]
    labels = metadata["Config"]["Labels"] if kind == "container" else metadata["Labels"]
    if labels.get("io.aqua.run") != run:
        raise RuntimeError("wrong_cleanup_owner")
    return metadata["Id"] if kind == "container" else name


def run(image: str, output: Path) -> int:
    run_backend.ROOT = ROOT
    source = run_backend.source_archive()
    commands.ROOT = resources.ROOT = ROOT
    commands.docker = resources.docker = docker
    commands.source_archive = resources.source_archive = lambda: source
    resources.owned_resource = owned
    name = "aqua-p05-browser-" + secrets.token_hex(12)
    fixture = resources.Resources(name)
    output = output / ("p11bc-composition-" + name[-24:])
    output.mkdir(parents=True)
    report = {
        "run": name,
        "source_sha256": hashlib.sha256(source).hexdigest(),
        "cleanup": False,
    }
    process = None
    try:
        runner = fixture.provision(image, report)
        pg = name + "-pg"
        prefix = b"\\set writer_password 'fixture-only'\n\\set recovery_password 'fixture-only'\n\\set checkpoint_password 'fixture-only'\n"
        docker(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            data=prefix + (ROOT / "ops/retirement/bootstrap.psql").read_bytes(),
        )
        sys.path.insert(0, str(ROOT / "backend"))
        from retirement.fingerprints import IdentityKey

        commitment = IdentityKey(
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            b"synthetic-fixture-HMAC-key-only!".ljust(32, b"0"),
        ).commitment.hex()
        prefix = (
            "\\set installation_id 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'\n\\set identity_key_id 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'\n\\set key_commitment '"
            + commitment
            + "'\n"
        ).encode()
        docker(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            data=prefix + (ROOT / "ops/retirement/schema.psql").read_bytes(),
        )
        hba = b"local all postgres peer\n"
        for role in ("aqua_app_runtime", "aqua_app_migrator", "aqua_app_backup"):
            hba += f"local aqua_app {role} scram-sha-256\n".encode()
        for role in (
            "aqua_retirement_writer",
            "aqua_retirement_recovery",
            "aqua_retirement_checkpoint",
        ):
            hba += f"local aqua_retirement {role} scram-sha-256\n".encode()
        hba += b"local all all reject\nhost all all 0.0.0.0/0 reject\nhost all all ::/0 reject\n"
        docker(
            "exec", "-i", pg, "tee", "/var/lib/postgresql/data/pg_hba.conf", data=hba
        )
        docker(
            "exec", pg, "psql", "-X", "-U", "postgres", "-c", "SELECT pg_reload_conf()"
        )
        process = subprocess.Popen(
            [
                DOCKER,
                "exec",
                "-i",
                "-e",
                "PYTHONPATH=/checks/backend:/checks/backend/tests",
                runner,
                "python",
                "/checks/tools/checks/retirement_fixture/integration_cases.py",
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        log = bytearray()
        buffer = bytearray()
        dump = None
        deadline = time.monotonic() + 110
        while process.poll() is None or selector.select(0):
            if time.monotonic() >= deadline:
                raise RuntimeError("composition_deadline")
            if not selector.select(min(0.5, deadline - time.monotonic())):
                continue
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                break
            log.extend(chunk)
            buffer.extend(chunk)
            if len(log) > 1024 * 1024:
                raise RuntimeError("composition_output_capacity")
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                if line == b"READY_FOR_BACKUP":
                    dump = docker(
                        "exec",
                        pg,
                        "pg_dump",
                        "-U",
                        "postgres",
                        "-d",
                        "aqua_app",
                        "--format=custom",
                        timeout=15,
                    )
                    if len(dump) > 8 * 1024 * 1024:
                        raise RuntimeError("fixture_dump_capacity")
                    report["synthetic_dump_sha256"] = hashlib.sha256(dump).hexdigest()
                    process.stdin.write(b"continue\n")
                    process.stdin.flush()
                elif line == b"READY_FOR_RESTORE":
                    if dump is None:
                        raise RuntimeError("fixture_dump_missing")
                    docker(
                        "exec",
                        "-i",
                        pg,
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
                    docker(
                        "exec",
                        "-i",
                        pg,
                        "psql",
                        "-X",
                        "-v",
                        "ON_ERROR_STOP=1",
                        "-U",
                        "postgres",
                        "-d",
                        "aqua_app",
                        data=(
                            ROOT / "ops/appdb/restore_session_fence.sql"
                        ).read_bytes(),
                    )
                    process.stdin.write(b"continue\n")
                    process.stdin.flush()
                elif line.startswith(b"{"):
                    report["composition"] = json.loads(line)
        report["exit_code"] = process.wait(timeout=5)
        (output / "cases.log").write_bytes(log)
        print(log.decode(errors="replace")[-12000:], flush=True)
    except Exception as error:
        report["error"] = type(error).__name__
    finally:
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        remaining = fixture.cleanup()
        report["cleanup"] = not remaining
        report["remaining"] = remaining
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(str(output), json.dumps(report), flush=True)
    return int(
        "error" in report
        or report.get("exit_code") != 0
        or not report["cleanup"]
        or report.get("composition", {}).get("status") != "passed"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image", default="aqua-checks:p00")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".check-results/retirement-integration"
    )
    arguments = parser.parse_args()
    if not arguments.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "Docker_actions": 0,
                    "production_DDL": False,
                }
            )
        )
    else:
        raise SystemExit(run(arguments.image, arguments.output))
