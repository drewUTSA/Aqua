"""Opt-in P12 workload in a fresh original-size fixture; exact owned cleanup."""

import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time

from mixed_capacity_contract import LIMITS
from mixed_capacity_docker import LocalDocker
import run_backend

IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")


def owned(name, expected, known, timeout, transport):
    result = transport.capture(
        "container",
        "inspect",
        name,
        "--format",
        '{{json .Id}} {{json .Name}} {{json .Image}} {{json (index .Config.Labels "io.aqua.purpose")}}',
        timeout=timeout,
    )
    absent = re.search(
        rb"no such (?:container|object):\s*" + re.escape(name.encode()) + rb"\s*$",
        result.stderr.lower(),
    )
    if result.returncode == 1 and result.stdout.strip() in {b"", b"[]"} and absent:
        return None
    if result.returncode or len(result.stdout) > 1024:
        raise ValueError("mixed_resource_inspection_unconfirmed")
    values = result.stdout.decode().strip().split()
    if len(values) != 4:
        raise ValueError("mixed_resource_shape_invalid")
    identifier, observed, image, purpose = map(json.loads, values)
    if (
        not re.fullmatch(r"[a-f0-9]{64}", identifier)
        or observed != "/" + name
        or image != expected
        or purpose != "p00-checks"
        or known is not None
        and identifier != known
    ):
        raise ValueError("mixed_resource_ownership_invalid")
    return identifier


def run_mixed(image: str, output: Path) -> int:
    if not IMAGE.fullmatch(image):
        raise ValueError("mixed_immutable_image_required")
    if (
        output.exists()
        or output.is_symlink()
        or any(parent.is_symlink() for parent in output.absolute().parents)
    ):
        raise ValueError("mixed_output_already_exists_or_unsafe")
    output.parent.mkdir(parents=True, exist_ok=True)
    transport = LocalDocker()
    run = "aqua-p12-mixed-" + secrets.token_hex(12)
    names = (run + "-pg", run + "-tests")
    known, expected = [], {}
    report = {
        "status": "failed",
        "mode": "mixed_http",
        "run": run,
        "image": image,
        "limits": LIMITS,
        "cleanup": "pending",
        "remaining_ids": [],
        "docker_context": transport.context,
        "local_transport": (
            "named_pipe" if transport.context == "desktop-linux" else "unix_socket"
        ),
    }
    original = run_backend.docker
    started = time.monotonic()
    deadline = started + LIMITS["whole_fixture_seconds"]

    def bounded(*arguments, data=None, timeout=60):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("mixed_whole_fixture_deadline")
        return transport.execute(*arguments, data=data, timeout=min(timeout, remaining))

    # Reserve the create-only receipt before the first fixture mutation. Names
    # are registered before ambiguous create calls, and never reused or pruned.
    with output.open("x", encoding="utf-8") as stream:
        try:
            run_backend.docker = bounded
            transport.verify(deadline)
            if (
                bounded("image", "inspect", image, "--format", "{{.Id}}").strip()
                != image.encode()
            ):
                raise ValueError("mixed_existing_exact_image_required")
            pg_image = (
                bounded("image", "inspect", run_backend.POSTGRES, "--format", "{{.Id}}")
                .decode()
                .strip()
            )
            if not IMAGE.fullmatch(pg_image):
                raise ValueError("mixed_existing_postgres_required")
            expected = {names[0]: pg_image, names[1]: image}
            archive = run_backend.source_archive()
            report["source_archive_sha256"] = hashlib.sha256(archive).hexdigest()
            report["postgres_image"] = pg_image
            _, runner = run_backend.provision_core(
                image=image, run_name=run, containers=known, archive=archive
            )
            operation = [
                "exec",
                "--workdir=/checks/backend",
                "-e",
                "PYTHONPATH=/checks/backend",
                runner,
                "python",
                "-B",
                "/checks/tools/checks/mixed_capacity_probe.py",
            ]
            duration = min(165, deadline - time.monotonic())
            if duration <= 0:
                raise TimeoutError("mixed_whole_fixture_deadline")
            result = transport.capture(*operation, timeout=duration)
            raw = result.stdout
            if len(raw) > 65536:
                raise ValueError("mixed_probe_output_bound")
            report["measurements"] = json.loads(raw)
            if result.returncode or report["measurements"].get("status") != "passed":
                raise ValueError("mixed_probe_incomplete")
            report["status"] = "passed"
        except BaseException as error:
            report["failure_category"] = type(error).__name__
        finally:
            run_backend.docker = original
            until = time.monotonic() + LIMITS["resource_cleanup_seconds"]

            def remaining():
                duration = min(15, until - time.monotonic())
                if duration <= 0:
                    raise TimeoutError("mixed_cleanup_deadline")
                return duration

            unresolved = []
            for name in reversed(names):
                try:
                    # No resources were attempted before exact image preflight.
                    if name not in expected:
                        continue
                    index = names.index(name)
                    registered = known[index] if len(known) > index else None
                    identifier = owned(
                        name, expected[name], registered, remaining(), transport
                    )
                    if identifier is not None:
                        transport.execute(
                            "rm", "--force", identifier, timeout=remaining()
                        )
                    if (
                        owned(name, expected[name], None, remaining(), transport)
                        is not None
                    ):
                        raise ValueError("mixed_cleanup_absence_unconfirmed")
                except (
                    RuntimeError,
                    ValueError,
                    OSError,
                    subprocess.TimeoutExpired,
                    TimeoutError,
                ):
                    unresolved.append(name)
            report["remaining_ids"] = unresolved
            report["cleanup"] = (
                "failed" if unresolved else "removed_and_absence_confirmed"
            )
            if unresolved:
                report["status"] = "failed"
            report["elapsed_seconds"] = round(time.monotonic() - started, 4)
            json.dump(report, stream, sort_keys=True, indent=2, allow_nan=False)
            stream.write("\n")
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    "status",
                    "mode",
                    "cleanup",
                    "remaining_ids",
                    "elapsed_seconds",
                )
            }
        )
    )
    return int(report["status"] != "passed")
