"""Prepare or run actual kernel protection using synthetic data, never a site.

Default is read-only. --execute is for the serialized native test slot, after
review, with an immutable image ID and a fresh expected-source fingerprint.
"""

import argparse
import hashlib
import json
import os
import re
import selectors
import subprocess
import time

import p05_browser_docker as commands
from retirement_durability_resources import (
    BASE,
    IMAGE,
    RUN,
    Resources,
    source,
    validate_base,
)


def private_directory(path) -> None:
    """Remove inherited setgid only on a newly created owned fixture inode."""
    path.mkdir(mode=0o700)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        current = os.fstat(fd)
        if current.st_uid != 1000 or (current.st_dev, current.st_ino) != (
            path.lstat().st_dev,
            path.lstat().st_ino,
        ):
            raise RuntimeError("durability_new_directory_identity_invalid")
        os.fchmod(fd, 0o700)
        os.fsync(fd)
    finally:
        os.close(fd)


def execute(image: str, expected: str, name: str = "") -> int:
    """Create only one new owner-only disposable tree under the QA directory."""
    if not IMAGE.fullmatch(image) or not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise RuntimeError("durability_exact_pins_required")
    if not RUN.fullmatch(name):
        raise RuntimeError("durability_exact_fresh_run_required")
    validate_base(BASE)
    contents, digest = source()
    if digest != expected:
        raise RuntimeError("durability_source_changed_after_review")
    if (
        commands.docker("image", "inspect", image, "--format={{.Id}}").strip()
        != image.encode()
    ):
        raise RuntimeError("durability_image_pin_mismatch")
    directory = BASE / name
    private_directory(directory)
    private_directory(directory / "source")
    private_directory(directory / "authority")
    for relative, raw in contents.items():
        path = directory / "source" / relative
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_bytes(raw)
        path.chmod(0o600)
    manifest = {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}
    (directory / "source-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n"
    )
    fixture = Resources(
        name,
        image,
        directory,
        contents["tools/checks/retirement_fixture/append_flags.py"],
    )
    report = {
        "run": name,
        "source_sha256": digest,
        "image_id": image,
        "production_changed": False,
        "private_inputs_read": False,
        "cleanup": False,
        "append_flags_cleared": False,
    }
    process = None
    log = bytearray()
    try:
        initializer = fixture.create("initialize")
        receipt = json.loads(
            commands.docker(
                "start", "--attach", initializer, timeout=fixture.remaining()
            )
        )
        if receipt.get("status") != "initialized":
            raise RuntimeError("durability_initializer_failed")
        if not fixture.remove("initialize"):
            raise RuntimeError("durability_initializer_exit_unconfirmed")
        report["initializer"] = receipt
        report["provisioning_sequence"] = ["initializer_removed_and_absence_confirmed"]
        fixture.flag("set")
        report["provisioning_sequence"].append("append_set_readback_and_setter_exit")
        identifier = fixture.create("probe")
        report["provisioning_sequence"].append("new_signer_created_after_flag")
        process = subprocess.Popen(
            [
                "/usr/bin/docker",
                "--host=unix:///var/run/docker.sock",
                "start",
                "--attach",
                "--interactive",
                identifier,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=commands.DOCKER_ENV,
            close_fds=True,
        )
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        buffer = bytearray()
        deadline = fixture.deadline
        while process.poll() is None or selector.select(0):
            if time.monotonic() >= deadline:
                raise RuntimeError("durability_probe_deadline")
            if not selector.select(min(0.2, deadline - time.monotonic())):
                continue
            chunk = os.read(process.stdout.fileno(), 16384)
            if not chunk:
                break
            log.extend(chunk)
            buffer.extend(chunk)
            if len(log) > 131072:
                raise RuntimeError("durability_output_capacity")
            while b"\n" in buffer:
                line, _, buffer = buffer.partition(b"\n")
                if line == b"READY_FOR_APPEND_FLAG":
                    raise RuntimeError("durability_signer_started_before_flag")
                elif line.startswith(b"{"):
                    report["kernel"] = json.loads(line)
        report["exit_code"] = process.wait(timeout=5)
    except Exception as error:
        report["error"] = type(error).__name__ + ":" + str(error)[:160]
    finally:
        # A dead Docker client does not prove its container child has exited.
        try:
            stopped = fixture.remove("probe") if "probe" in fixture.attempted else True
            if stopped and all(
                (directory / "authority" / file).exists()
                for file in ("checkpoints.bin", "poison.bin")
            ):
                fixture.flag("clear")
                report["append_flags_cleared"] = True
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            report["cleanup_error"] = "fixture_inode_cleanup_unconfirmed"
        if process is not None and process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        remaining = []
        for role in reversed(fixture.attempted):
            try:
                if not fixture.remove(role):
                    remaining.append(role)
            except (RuntimeError, OSError, subprocess.TimeoutExpired):
                remaining.append(role)
        report["remaining_containers"] = remaining
        files_removed = False
        if report["append_flags_cleared"]:
            try:
                for file in ("checkpoints.bin", "poison.bin", "replacement.bin"):
                    (directory / "authority" / file).unlink(missing_ok=True)
                (directory / "authority").rmdir()
                files_removed = True
            except OSError:
                report["cleanup_error"] = "fixture_file_cleanup_unconfirmed"
        report["cleanup"] = not remaining and files_removed
        (directory / "probe.log").write_bytes(log)
        (directory / "report.json").write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({"directory": str(directory), **report}, sort_keys=True))
    return int(
        report.get("exit_code") != 0
        or report.get("kernel", {}).get("status") != "passed"
        or not report["cleanup"]
        or "error" in report
    )


def main() -> int:
    """Printing a reviewable plan never opens Docker or writes fixture files."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--image", default="")
    parser.add_argument("--source-sha256", default="")
    parser.add_argument("--run", default="")
    arguments = parser.parse_args()
    if not arguments.execute:
        contents, digest = source()
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "Docker_actions": 0,
                    "writes": 0,
                    "source_sha256": digest,
                    "source_files": len(contents),
                    "requires_linux_uid": 1000,
                    "fixture_base": str(BASE),
                    "setter_capabilities": [
                        "LINUX_IMMUTABLE",
                        "FOWNER",
                        "DAC_OVERRIDE",
                    ],
                    "signer_capabilities": [],
                    "private_inputs": False,
                    "native_execution_held_until_coordinator_release": True,
                },
                sort_keys=True,
            )
        )
        return 0
    return execute(arguments.image, arguments.source_sha256, arguments.run)


if __name__ == "__main__":
    raise SystemExit(main())
