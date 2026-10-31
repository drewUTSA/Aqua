"""Run only the new real32MiB case in fresh unchanged-size private fixtures.

No old testcase is moved/deselected. The ordinary matrix and this exact case
must all pass; real JUnit is merged before coverage/retention checks. Fresh
fixtures isolate this capacity exercise from accumulated matrix migration WAL.
"""

from copy import deepcopy
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET

from app_fixture import initialize

CAPACITY_CASE = "tests/test_privacy_exports.py::test_json_escaping_over_output_cap_rolls_back_instead_of_truncating"
CLASS = "tests.test_privacy_exports"
TEST = CAPACITY_CASE.split("::")[1]
POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)


def selected_case(path):
    if path.is_symlink() or not 1 <= path.stat().st_size <= 1024**2:
        raise RuntimeError("capacity_junit_boundary_invalid")
    document = ET.parse(path)
    cases = list(document.iter("testcase"))
    suites = list(document.iter("testsuite"))
    if (
        len(cases) != 1
        or len(suites) != 1
        or any(
            suites[0].get(key) != value
            for key, value in (
                ("tests", "1"),
                ("errors", "0"),
                ("failures", "0"),
                ("skipped", "0"),
            )
        )
        or (cases[0].get("classname"), cases[0].get("name")) != (CLASS, TEST)
        or any(
            cases[0].find(tag) is not None for tag in ("failure", "error", "skipped")
        )
    ):
        raise RuntimeError("capacity_exact_case_not_passed")
    return document


def merge_junit(core, capacity):
    """Retain all actual core suites; append one actual disjoint passed case."""
    extra = selected_case(capacity)
    if core.is_symlink() or not 1 <= core.stat().st_size <= 4 * 1024**2:
        raise RuntimeError("capacity_core_junit_boundary_invalid")
    original = core.read_bytes()
    document = ET.parse(core)
    if any(
        (case.get("classname"), case.get("name")) == (CLASS, TEST)
        for case in document.iter("testcase")
    ):
        raise RuntimeError("capacity_case_already_in_core")
    root = document.getroot()
    if root.tag != "testsuites" or extra.getroot().tag != "testsuites":
        raise RuntimeError("capacity_junit_structure_invalid")
    suites = list(extra.getroot())
    if len(suites) != 1 or suites[0].tag != "testsuite":
        raise RuntimeError("capacity_junit_structure_invalid")
    root.append(deepcopy(suites[0]))
    document.write(core, encoding="utf-8", xml_declaration=True)
    cases = [
        case
        for case in document.iter("testcase")
        if (case.get("classname"), case.get("name")) == (CLASS, TEST)
    ]
    if len(cases) != 1:
        raise RuntimeError("capacity_merge_identity_invalid")
    with (core.parent / ("core-" + core.name)).open("xb") as output:
        output.write(original)
    return {
        "core_sha256": hashlib.sha256(original).hexdigest(),
        "capacity_sha256": hashlib.sha256(capacity.read_bytes()).hexdigest(),
        "merged_sha256": hashlib.sha256(core.read_bytes()).hexdigest(),
        "capacity_identity_count": 1,
    }


def verify(docker, create, source, image, run_name, output, archive):
    report = {
        "status": "failed",
        "kind": "fresh_exact_private_export_capacity",
        "testcase": CAPACITY_CASE,
        "backend_image": image,
        "schema_version": 8,
        "postgres_data_bytes": 536870912,
        "container_memory_bytes": 1073741824,
        "real_export_output_limit_bytes": 33554432,
        "existing_test_deselections": 0,
        "results": [],
        "cleanup": "pending",
        "remaining_ids": [],
    }
    for dataset in ("bank", "pagila"):
        owned = []
        result = {"dataset": dataset, "exit_code": None, "status": "failed"}
        started = time.monotonic()
        try:
            pg = create(
                run_name + "-capacity-" + dataset + "-pg",
                POSTGRES,
                "--network=none",
                "--user=999:999",
                "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
                "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864",
                "-e",
                "POSTGRES_HOST_AUTH_METHOD=trust",
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
            owned.append(pg)
            docker("start", pg)
            until = time.monotonic() + 45
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
                    if time.monotonic() >= until:
                        raise RuntimeError("capacity_fixture_start_deadline") from None
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
                data=b"CREATE ROLE nl2sql_reader LOGIN; ALTER ROLE nl2sql_reader SET default_transaction_read_only=on; ALTER ROLE nl2sql_reader SET statement_timeout='100ms'; CREATE DATABASE aqua_test_bank; CREATE DATABASE aqua_test_pagila;",
            )
            for fixture in ("bank", "pagila"):
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
                    "aqua_test_" + fixture,
                    data=(
                        source / "tools/checks/fixtures" / (fixture + ".sql")
                    ).read_bytes(),
                )
            initialize(docker, pg, source)
            result["initial_database_tmpfs"] = (
                docker("exec", pg, "df", "-k", "/var/lib/postgresql/data")
                .decode()
                .splitlines()[-1]
                .split()[1:5]
            )
            runner = create(
                run_name + "-capacity-" + dataset + "-tests",
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
                command=("120",),
            )
            owned.append(runner)
            docker("start", runner)
            docker(
                "exec",
                "-i",
                runner,
                "python",
                "-c",
                "import io,sys,tarfile;tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read())).extractall('/checks',filter='data')",
                data=archive,
            )
            process = subprocess.run(
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
                    "--junitxml=/tmp/capacity.xml",
                    CAPACITY_CASE,
                ],
                capture_output=True,
                timeout=60,
            )
            result["exit_code"] = process.returncode
            (output / ("capacity-" + dataset + ".txt")).write_bytes(
                process.stdout + process.stderr
            )
            target = output / ("capacity-" + dataset + ".xml")
            target.write_bytes(docker("exec", runner, "cat", "/tmp/capacity.xml"))
            result["final_database_tmpfs"] = (
                docker("exec", pg, "df", "-k", "/var/lib/postgresql/data")
                .decode()
                .splitlines()[-1]
                .split()[1:5]
            )
            if process.returncode != 0:
                raise RuntimeError("capacity_test_process_failed")
            selected_case(target)
            result["status"] = "passed"
        except (
            RuntimeError,
            AssertionError,
            subprocess.TimeoutExpired,
            OSError,
            ET.ParseError,
        ) as error:
            result["failure_category"] = type(error).__name__
        finally:
            remaining = []
            for container in reversed(owned):
                try:
                    docker("rm", "--force", container)
                    state = subprocess.run(
                        ["docker", "container", "inspect", container],
                        capture_output=True,
                        timeout=15,
                    )
                    if state.returncode != 1 or b"No such" not in state.stderr:
                        remaining.append(container)
                except (RuntimeError, subprocess.TimeoutExpired):
                    remaining.append(container)
            result["cleanup"] = (
                "removed_and_absence_confirmed" if not remaining else "failed"
            )
            result["remaining_ids"] = remaining
            result["seconds"] = round(time.monotonic() - started, 2)
            report["remaining_ids"].extend(remaining)
            report["results"].append(result)
    if len(report["results"]) == 2 and all(
        item["status"] == "passed"
        and item["exit_code"] == 0
        and item["cleanup"] == "removed_and_absence_confirmed"
        and not item["remaining_ids"]
        for item in report["results"]
    ):
        try:
            report["junit"] = {
                dataset: merge_junit(
                    output / (dataset + ".xml"),
                    output / ("capacity-" + dataset + ".xml"),
                )
                for dataset in ("bank", "pagila")
            }
            report["status"] = "passed"
            report["junit_merge"] = "actual_disjoint_testcase_identity_once_per_dataset"
        except (RuntimeError, OSError, ET.ParseError) as error:
            report["failure_category"] = type(error).__name__
    report["cleanup"] = (
        "removed_and_absence_confirmed" if not report["remaining_ids"] else "failed"
    )
    (output / "privacy-capacity.json").write_text(json.dumps(report, indent=2) + "\n")
    return report
