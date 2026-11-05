"""Execute complete backend inventories in sequential, same-budget fixtures."""

import json
from collections.abc import Callable
from pathlib import Path
import subprocess

from backend_batches import BATCH_COUNT, merge, plan

Docker = Callable[..., bytes]
Provision = Callable[[str, str, list[str], bytes], tuple[str, str]]
Restore = Callable[[Docker, str, str], dict]


def execute(command: list[str], timeout: int, log: Path) -> None:
    """Retain bounded progress diagnostics when the subprocess deadline fires."""
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        partial = (error.stdout or b"") + (error.stderr or b"")
        log.write_bytes(partial[-65536:])
        print(partial[-65536:].decode(errors="replace"))
        raise RuntimeError("backend_command_timeout:" + log.name) from None
    log.write_bytes(result.stdout + result.stderr)
    print((result.stdout + result.stderr).decode(errors="replace"))
    if result.returncode:
        raise RuntimeError("backend_command_failed:" + log.name)


def diagnostics(
    docker: Docker, pg: str, dataset: str, batch: str, report: dict
) -> None:
    """Best-effort metadata only; preserve the original test failure."""
    result = {"dataset": dataset, "batch": batch}
    try:
        logs = subprocess.run(
            ["docker", "logs", "--tail", "100", pg],
            capture_output=True,
            timeout=15,
        )
        if logs.returncode:
            raise RuntimeError("fixture_logs_unavailable")
        # Docker preserves PostgreSQL's stderr stream. The usual docker helper
        # returns stdout only, which would silently hide these crash messages.
        log = (logs.stdout + logs.stderr)[-65536:].decode(errors="replace")
        result["database_categories"] = [
            category
            for category in (
                "No space left on device",
                "out of memory",
                "PANIC",
                "database system is in recovery mode",
            )
            if category in log
        ]
    except (RuntimeError, subprocess.TimeoutExpired):
        result["database_categories_unavailable"] = True
    for key, command in (
        ("database_oom_killed", ("inspect", pg, "--format", "{{.State.OOMKilled}}")),
        ("database_tmpfs", ("exec", pg, "df", "-k", "/var/lib/postgresql/data")),
    ):
        try:
            raw = docker(*command).decode()
            result[key] = (
                raw.strip() == "true"
                if key == "database_oom_killed"
                else raw.splitlines()[-1].split()[1:5]
            )
        except (RuntimeError, subprocess.TimeoutExpired, IndexError):
            result[key + "_unavailable"] = True
    report.setdefault("fixture_diagnostics", []).append(result)


def run_core(
    docker: Docker,
    provision: Provision,
    restore: Restore,
    archive: bytes,
    image: str,
    run_name: str,
    containers: list[str],
    output: Path,
    report: dict,
    capacity_case: str,
) -> None:
    """Require full default collection, exact JUnit identities and exact cleanup."""
    for dataset in ("bank", "pagila"):
        batches = None
        for index in range(BATCH_COUNT):
            batch_id = f"{index + 1:02}"
            pg, runner = provision(
                image, f"{run_name}-{dataset}-{batch_id}", containers, archive
            )
            row = {"dataset": dataset, "batch": batch_id, "status": "started"}
            report.setdefault("core_batches", []).append(row)
            command = [
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
                "-u",
            ]
            try:
                if batches is None:
                    execute(
                        command
                        + [
                            "/checks/tools/checks/backend_batches.py",
                            "--collect=/tmp/collection.json",
                            "--deselect=" + capacity_case,
                        ],
                        60,
                        output / (dataset + "-collection.txt"),
                    )
                    raw = docker("exec", runner, "cat", "/tmp/collection.json")
                    (output / (dataset + "-collection.json")).write_bytes(raw)
                    inventory = json.loads(raw)
                    batches = inventory["batches"]
                    if (
                        inventory["schema"] != 1
                        or plan([case for batch in batches for case in batch["cases"]])
                        != batches
                    ):
                        raise RuntimeError("backend_collection_plan_mismatch")
                batch = batches[index]
                row.update({"modules": batch["modules"], "cases": len(batch["cases"])})
                stem = f"{dataset}-batch-{batch_id}"
                execute(
                    command
                    + [
                        "-m",
                        "pytest",
                        "-vv",
                        "-p",
                        "no:cacheprovider",
                        "--tb=short",
                        "--junitxml=/tmp/batch.xml",
                        "--deselect=" + capacity_case,
                        *batch["modules"],
                    ],
                    120,
                    output / (stem + ".txt"),
                )
                (output / (stem + ".xml")).write_bytes(
                    docker("exec", runner, "cat", "/tmp/batch.xml")
                )
                restored = restore(docker, pg, runner)
                row["app_restore"] = restored
                report.setdefault("app_restore_by_dataset", {})[dataset] = restored
                report["app_restore"] = restored
                packages = docker("exec", runner, "python", "-m", "pip", "freeze")
                (output / (stem + "-packages.txt")).write_bytes(packages)
                reference = output / "packages.txt"
                if not reference.exists():
                    reference.write_bytes(packages)
                elif packages != reference.read_bytes():
                    raise RuntimeError("dataset_dependency_image_changed")
                row["status"] = "passed"
            except (RuntimeError, subprocess.TimeoutExpired):
                row["status"] = "failed"
                diagnostics(docker, pg, dataset, batch_id, report)
                raise
            # No subsequent batch/dataset/capacity pair until exact absence.
            for container in reversed(containers[:]):
                docker("rm", "--force", container)
                state = subprocess.run(
                    ["docker", "container", "inspect", container],
                    capture_output=True,
                    timeout=15,
                )
                if state.returncode != 1 or b"No such" not in state.stderr:
                    raise RuntimeError("core_fixture_cleanup_unconfirmed")
                containers.remove(container)
            row["cleanup"] = "removed_and_absence_confirmed"
            if index + 1 == len(batches):
                break
        merged = merge(output, dataset, batches)
        report["results"].append({"dataset": dataset, "exit_code": 0, **merged})
        report.setdefault("core_dataset_cleanup", []).append(
            {"dataset": dataset, "status": "removed_and_absence_confirmed"}
        )
        # Compatibility log/package paths retain every real batch, in order.
        (output / (dataset + ".txt")).write_bytes(
            b"\n".join(
                (output / f"{dataset}-batch-{batch['id']}.txt").read_bytes()
                for batch in batches
            )
        )
        (output / (dataset + "-packages.txt")).write_bytes(
            (output / "packages.txt").read_bytes()
        )
    report["core_fixture_cleanup"] = "removed_and_absence_confirmed"
