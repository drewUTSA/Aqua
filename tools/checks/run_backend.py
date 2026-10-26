"""Run backend checks in disposable containers without host ports or live config.

Requires a prebuilt dependency image (tools/checks/Dockerfile) and the pinned
PostgreSQL image. Source is copied through stdin; no host directories are mounted.
Docker access is privileged: use only a trusted checkout, never untrusted PR
code on the production server. CI runs this on an ephemeral hosted runner.
"""

import argparse
import io
import json
from pathlib import Path
import secrets
import subprocess
import tarfile
import time

from matrix import coverage
from app_fixture import initialize
from app_restore import verify as verify_restore

ROOT = Path(__file__).resolve().parents[2]
POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)


def docker(*args: str, data: bytes | None = None, timeout: int = 60) -> bytes:
    """Bound every Docker operation and surface failures rather than skipping."""
    result = subprocess.run(
        ["docker", *args], input=data, capture_output=True, timeout=timeout
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode(errors="replace")[-2000:])
    return result.stdout


def source_archive() -> bytes:
    """Copy only code/fixtures from known paths; never package .env or Git data."""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for folder in ("backend", "eval", "tools/checks", "ops"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_symlink():
                    raise RuntimeError("symlink in check source")
                asset = path.parent == ROOT / "backend/auth" and path.name in {
                    "password_blocklist_sha256.txt",
                    "password_blocklist_LICENSE.txt",
                    "password_blocklist_provenance.json",
                }
                if not path.is_file() or (
                    not asset
                    and path.suffix
                    not in {
                        ".py",
                        ".sql",
                        ".psql",
                        ".ini",
                    }
                ):
                    continue
                if any(
                    p.startswith(".") or p in {"__pycache__", "results"}
                    for p in path.relative_to(ROOT).parts
                ):
                    continue
                content = path.read_bytes()
                info = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
                info.size, info.mode, info.uid, info.gid = (
                    len(content),
                    0o644,
                    1000,
                    1000,
                )
                archive.addfile(info, io.BytesIO(content))
    return stream.getvalue()


def create(name: str, image: str, *args: str, command: tuple[str, ...] = ()) -> str:
    """All resources are run-specific and resource-limited; never reuse services."""
    return (
        docker(
            "create",
            "--name",
            name,
            "--label",
            "io.aqua.purpose=p00-checks",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--memory=1g",
            "--memory-swap=1g",
            "--cpus=2",
            "--pids-limit=256",
            "--log-driver=local",
            "--log-opt=max-size=2m",
            "--log-opt=max-file=2",
            *args,
            image,
            *command,
        )
        .decode()
        .strip()
    )


def run(image: str, output: Path) -> int:
    """Run both fixture datasets; report cleanup even when a test fails."""
    run_name = "aqua-check-" + secrets.token_hex(12)
    containers: list[str] = []
    report: dict = {"run": run_name, "results": [], "cleanup": "not_started"}
    output.mkdir(parents=True, exist_ok=True)
    try:
        report["backend_image"] = (
            docker("image", "inspect", image, "--format", "{{.Id}}").decode().strip()
        )
        report["postgres_image"] = (
            docker("image", "inspect", POSTGRES, "--format", "{{.Id}}").decode().strip()
        )
        pg = create(
            run_name + "-pg",
            POSTGRES,
            "--network=none",
            "--user=999:999",
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
            "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            # Repeated disposable schema migrations generate WAL faster than
            # the default five-minute checkpoint on this bounded tmpfs.
            command=(
                "postgres",
                "-c",
                "max_wal_size=128MB",
                "-c",
                "min_wal_size=32MB",
                "-c",
                "checkpoint_timeout=30s",
            ),
        )
        containers.append(pg)
        docker("start", pg)
        deadline = time.monotonic() + 45
        while True:
            try:
                docker(
                    "exec",
                    pg,
                    "pg_isready",
                    "-h",
                    "127.0.0.1",
                    "-U",
                    "postgres",
                    timeout=5,
                )
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "disposable PostgreSQL did not become ready"
                    ) from None
                time.sleep(0.5)
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
            data=b"""
            CREATE ROLE nl2sql_reader LOGIN;
            ALTER ROLE nl2sql_reader SET default_transaction_read_only = on;
            ALTER ROLE nl2sql_reader SET statement_timeout = '100ms';
            CREATE DATABASE aqua_test_bank;
            CREATE DATABASE aqua_test_pagila;
        """,
        )
        for dataset in ("bank", "pagila"):
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
                "aqua_test_" + dataset,
                data=(ROOT / "tools/checks/fixtures" / (dataset + ".sql")).read_bytes(),
            )
        initialize(docker, pg, ROOT)
        runner = create(
            run_name + "-tests",
            image,
            "--network=container:" + pg,
            "--user=1000:1000",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=268435456,mode=1777",
            "--tmpfs=/checks:rw,nosuid,nodev,size=67108864,mode=0777",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
            "-e",
            "PYTHON_DOTENV_DISABLED=1",
            "--workdir=/tmp",
            "--entrypoint=/bin/sleep",
            command=("300",),
        )
        # The image CMD is a bounded sleep; the app entry point never runs.
        containers.append(runner)
        docker("start", runner)
        unpack = "import io,sys,tarfile;tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall('/checks',filter='data')"
        docker("exec", "-i", runner, "python", "-c", unpack, data=source_archive())
        for dataset in ("bank", "pagila"):
            result = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-w",
                    "/checks/backend",
                    "-e",
                    "AQUA_TEST_DATASET=" + dataset,
                    "-e",
                    "AQUA_TEST_APP_STORAGE=1",
                    runner,
                    "python",
                    "-m",
                    "pytest",
                    "-q",
                    "-p",
                    "no:cacheprovider",
                    "--tb=short",
                    "--junitxml=/tmp/" + dataset + ".xml",
                ],
                capture_output=True,
                timeout=120,
            )
            log = result.stdout + result.stderr
            (output / (dataset + ".txt")).write_bytes(log)
            report["results"].append(
                {"dataset": dataset, "exit_code": result.returncode}
            )
            if result.returncode:
                fixture_log = docker("logs", "--tail", "100", pg).decode(
                    errors="replace"
                )
                report.setdefault("fixture_diagnostics", []).append(
                    {
                        "dataset": dataset,
                        "database_tmpfs": docker(
                            "exec", pg, "df", "-k", "/var/lib/postgresql/data"
                        )
                        .decode()
                        .splitlines()[-1]
                        .split()[1:5],
                        "database_oom_killed": docker(
                            "inspect", pg, "--format", "{{.State.OOMKilled}}"
                        )
                        .decode()
                        .strip()
                        == "true",
                        "database_categories": [
                            category
                            for category in (
                                "No space left on device",
                                "out of memory",
                                "PANIC",
                                "database system is in recovery mode",
                            )
                            if category in fixture_log
                        ],
                    }
                )
            (output / (dataset + ".xml")).write_bytes(
                docker("exec", runner, "cat", "/tmp/" + dataset + ".xml")
            )
            print(log.decode(errors="replace"))
        # Record immutable versions used, without inspecting runtime environments.
        report["coverage"] = coverage(output)
        report["app_restore"] = verify_restore(docker, pg)
        (output / "packages.txt").write_bytes(
            docker("exec", runner, "python", "-m", "pip", "freeze")
        )
    except (RuntimeError, AssertionError, subprocess.TimeoutExpired) as error:
        report["error"] = str(error)
    finally:
        cleanup_errors = []
        for container in reversed(containers):
            try:
                docker("rm", "--force", container)
                check = subprocess.run(
                    ["docker", "container", "inspect", container],
                    capture_output=True,
                    timeout=15,
                )
                if check.returncode != 1 or b"No such" not in check.stderr:
                    cleanup_errors.append(container)
            except (RuntimeError, subprocess.TimeoutExpired):
                cleanup_errors.append(container)
        report["cleanup"] = (
            "failed" if cleanup_errors else "removed_and_absence_confirmed"
        )
        report["remaining_ids"] = cleanup_errors
        (output / "report.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
        print(json.dumps(report))
    return int(
        "error" in report
        or report["cleanup"] == "failed"
        or len(report["results"]) != 2
        or any(r["exit_code"] for r in report["results"])
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", default="aqua-checks:p00")
    parser.add_argument("--output", type=Path, default=ROOT / ".check-results/backend")
    args = parser.parse_args()
    raise SystemExit(run(args.image, args.output))
