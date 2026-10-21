"""Explicit operator review step for NEW dedicated storage, never shared data."""

import argparse
import json
import os
from pathlib import Path
import secrets
import subprocess
import time

from private import credentials, directory, prepare

ROOT = Path(__file__).resolve().parents[2]
CONTAINER = "aqua-app-db"
VOLUME = "aqua_app_data"
SOCKET_VOLUME = "aqua_app_sockets"
BACKEND_IMAGE = "bank-ai-backend"
IMAGE = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)


def run(args: list[str], data: bytes | None = None, timeout: int = 60) -> bytes:
    result = subprocess.run(
        args,
        input=data,
        capture_output=True,
        cwd=ROOT,
        timeout=timeout,
        env={**os.environ, "AQUA_PRIVATE_STORAGE_DIR": str(directory())},
    )
    if result.returncode:
        raise RuntimeError("application_storage_command_failed_output_redacted")
    return result.stdout


def docker(*args: str, data: bytes | None = None) -> bytes:
    return run(["/usr/bin/docker", *args], data)


def absent(kind: str, name: str) -> None:
    result = subprocess.run(
        ["/usr/bin/docker", kind, "inspect", name], capture_output=True, timeout=15
    )
    missing = any(text in result.stderr.lower() for text in (b"no such", b"not found"))
    if result.returncode != 1 or not missing:
        raise RuntimeError("resource_already_exists_or_inspection_failed")


def bootstrap() -> dict:
    prepare()
    for kind, name in [
        ("container", CONTAINER),
        ("volume", VOLUME),
        ("volume", SOCKET_VOLUME),
    ]:
        absent(kind, name)
    nonce = secrets.token_hex(12)
    docker("image", "inspect", IMAGE)
    for name, owner in [(VOLUME, "999:999"), (SOCKET_VOLUME, "999:1000")]:
        docker("volume", "create", "--label", "io.aqua.install=" + nonce, name)
        volume = json.loads(docker("volume", "inspect", name))[0]
        if volume.get("Labels", {}).get("io.aqua.install") != nonce:
            raise RuntimeError("new_volume_ownership_check_failed")
        # Only adjust the root of each newly created, labelled volume.
        docker(
            "run",
            "--rm",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--cap-add=CHOWN",
            "--memory=64m",
            "--cpus=1",
            "--pids-limit=32",
            "--mount",
            "source=" + name + ",target=/new-volume",
            "--entrypoint=sh",
            IMAGE,
            "-c",
            "chmod 0770 /new-volume && chown " + owner + " /new-volume",
        )
    try:
        run(
            [
                "/usr/bin/docker",
                "compose",
                "-f",
                str(ROOT / "compose.appdb.yml"),
                "up",
                "-d",
                "--no-build",
            ],
            timeout=90,
        )
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            state = json.loads(docker("inspect", CONTAINER))[0]["State"]
            if state.get("Health", {}).get("Status") == "healthy":
                break
            if not state.get("Running"):
                raise RuntimeError("private_database_stopped_during_startup")
            time.sleep(1)
        else:
            raise RuntimeError("private_database_startup_timeout")
        data = credentials()
        prefix = "".join(
            f"\\set {name}_password '{data[name]}'\n"
            for name in ("runtime", "migrator", "backup")
        ).encode()
        docker(
            "exec",
            "-i",
            CONTAINER,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            data=prefix + (ROOT / "backend/migrations/bootstrap.psql").read_bytes(),
        )
        item = json.loads(docker("inspect", CONTAINER))[0]
        if (
            item["HostConfig"]["PortBindings"]
            or item["HostConfig"]["NetworkMode"] != "none"
        ):
            raise RuntimeError("unexpected_database_network_exposure")
        return {
            "status": "bootstrapped",
            "database": "aqua_app",
            "public_database_port": False,
            "schema_migrated": False,
        }
    except Exception:
        subprocess.run(
            ["/usr/bin/docker", "stop", CONTAINER], capture_output=True, timeout=20
        )
        # Preserve every volume/credential on partial failure; never reset data.
        raise


def migrate() -> dict:
    # No analytical, Google or email environment is supplied to the one-off tool.
    nonce = secrets.token_hex(12)
    name = "aqua-app-migrate-" + nonce
    try:
        result = docker(
            "run",
            "--rm",
            "--name",
            name,
            "--label",
            "io.aqua.migration=" + nonce,
            "--network=none",
            "--mount",
            "source=" + SOCKET_VOLUME + ",target=/run/aqua-app-db,readonly",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--memory=512m",
            "--cpus=1",
            "--pids-limit=128",
            "--env-file",
            str(directory() / "migrator.env"),
            "--entrypoint=python",
            BACKEND_IMAGE,
            "-m",
            "storage.migrate",
        )
    finally:
        check = subprocess.run(
            ["/usr/bin/docker", "inspect", name], capture_output=True, timeout=10
        )
        if check.returncode == 0:
            item = json.loads(check.stdout)[0]
            if item["Config"].get("Labels", {}).get("io.aqua.migration") != nonce:
                raise RuntimeError("migration_resource_ownership_changed")
            docker("rm", "--force", item["Id"])
    if result.strip() != b"application_schema_version=3":
        raise RuntimeError("unexpected_migration_result")
    return {"status": "migrated", "schema_version": 3, "public_signup_enabled": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["prepare", "bootstrap", "migrate"])
    parser.add_argument("--apply-reviewed", action="store_true")
    args = parser.parse_args()
    if args.action != "prepare" and not args.apply_reviewed:
        raise RuntimeError("migration_and_infrastructure_review_required")
    if args.action == "prepare":
        prepare()
        result = {
            "status": "private_files_prepared",
            "directory": str(directory()),
            "secrets_displayed": False,
        }
    else:
        result = bootstrap() if args.action == "bootstrap" else migrate()
    print(json.dumps(result))


if __name__ == "__main__":
    main()
