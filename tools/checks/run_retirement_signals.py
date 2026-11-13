"""Closed 48 publisher controls: actual children/signals, modeled private/RPC IO."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tools/checks/retirement_fixture/publisher_signals"
TEST_SHA = "b6cae0bcb1bc8a4f5939e4978afb25eb2cd61caf337dfa098c97e3c7200456fb"
CHILD_SHA = "44ea122497a143c615eb8b1b09db84cfcb4b44caa9194754c3503631ae331542"
LAUNCHER_SHA = "37452a4aee1a63ec1f2cce9fcae8be3de2b6d015ef2d0e824e4dfe4ab6b8fe66"
SCOPE_SHA = "f6064b65a190dd87769b2878b4b43bed598d3c99dd0bfa8f4b799e13ad6d5d2d"
ORIGINAL_TEST_SHA = "b7f91e2c3e6c688843a1fba70c15d342b044d2daa7ffb14114381e0354a48139"
ORIGINAL_CHILD_SHA = "a8faabf743f0d8082f711ff172e417d8f6ebec0ea4ad81e2a5cd73aa8d44ebae"
EXPECTED = (
    "prepared",
    "idle",
    "checked",
    "busy",
    "create_TERM",
    "create_INT",
    "start_TERM",
    "start_INT",
    "repeat_TERM",
    "repeat_INT",
    "cleanup_false",
    "error_RuntimeError",
    "error_KeyboardInterrupt",
    "error_SystemExit",
    "registration_failure",
    "print_signal",
    "invalid_pin",
    "normal_cleanup_TERM",
    "normal_cleanup_INT",
    "normal_cleanup_repeat_TERM",
    "normal_cleanup_repeat_INT",
    "normal_rm_repeat_TERM",
    "normal_rm_repeat_INT",
    "create_failure_TERM",
    "create_failure_INT",
    "direct_idle",
    "direct_busy",
    "direct_cleanup_false",
    "direct_start_TERM",
    "direct_start_INT",
    "direct_normal_cleanup_TERM",
    "direct_normal_cleanup_INT",
    "direct_normal_cleanup_repeat_TERM",
    "direct_normal_cleanup_repeat_INT",
    "direct_normal_rm_repeat_TERM",
    "direct_normal_rm_repeat_INT",
    "direct_create_failure_TERM",
    "direct_registration_failure",
    "direct_nonmain_thread",
    "direct_reentrant",
    "direct_before_launch_TERM",
    "direct_before_launch_INT",
    "external_start_TERM",
    "external_start_INT",
    "external_normal_cleanup_TERM",
    "external_normal_cleanup_INT",
    "direct_external_normal_cleanup_TERM",
    "direct_external_normal_cleanup_INT",
)
FAILURE_CATEGORIES = frozenset(
    {
        "AssertionError",
        "ValueError",
        "JSONDecodeError",
        "KeyError",
        "TimeoutExpired",
        "prior_handlers_not_restored",
        "active_guard_latched",
        "requested_signal_not_observed",
        "unredacted_entrypoint_output",
        "unredacted_exception_context",
        "direct_execute_printed_output",
        "fixed_unavailable_output_missing",
        "actual_cleanup_not_completed",
        "repeat_signal_not_observed",
        "child_signal_readiness_deadline",
        "child_output_bound",
        "child_result_missing_after_signal",
        "unexpected_child_stderr",
        "child_exit_mismatch",
        "unclassified",
    }
)


def public_diagnostic(result, source):
    """Only fixed case IDs/categories and numeric facts; never child text."""
    value = {
        "schemaVersion": 1,
        "source_sha256": source,
        "process_exit_code": result.returncode,
        "stdout_bytes": len(result.stdout),
        "stderr_bytes": len(result.stderr),
        "reported_tests": None,
        "failed_cases": [],
        "summary_decoded": False,
    }
    if not 0 < len(result.stdout) <= 65536:
        return value
    try:
        report = decode(result.stdout)
        rows = report.get("outcomes") if type(report) is dict else None
        if (
            type(rows) is not list
            or len(rows) != 48
            or not all(type(row) is dict for row in rows)
            or tuple(row.get("case") for row in rows) != EXPECTED
            or type(report.get("tests")) is not int
            or report["tests"] != 48
        ):
            return value
        value["reported_tests"] = 48
        for row in rows:
            if row.get("passed") is not True:
                category = row.get("failure_category") or "AssertionError"
                value["failed_cases"].append(
                    {
                        "case": row["case"],
                        "category": (
                            category
                            if category in FAILURE_CATEGORIES
                            else "unclassified"
                        ),
                    }
                )
        value["summary_decoded"] = True
    except (ValueError, TypeError, UnicodeError, RuntimeError):
        pass
    return value


def require(condition):
    if not condition:
        raise RuntimeError("publisher_signals_closed_controls_failed")


def decode(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            require(key not in out)
            out[key] = value
        return out

    return json.loads(raw, object_pairs_hook=pairs)


def validate(value, source):
    require(
        type(value) is dict
        and type(value.get("tests")) is int
        and value["tests"] == 48
        and type(value.get("passed")) is int
        and value["passed"] == 48
        and type(value.get("failed")) is int
        and value["failed"] == 0
        and value.get("source_sha256") == source
        and value.get("launcher_sha256") == LAUNCHER_SHA
        and value.get("child_runner_sha256") == CHILD_SHA
        and value.get("external_posix_delivery") == {"status": "passed", "count": 6}
        and type(value["external_posix_delivery"]["count"]) is int
        and value.get("focused_baseline") is False
        and value.get("child_timeout_seconds") == 10
        and type(value["child_timeout_seconds"]) is int
        and value.get("native_Docker_private_files_services_network") is False
        and value.get("actual_Docker_clean_exercised") is True
        and value.get("native_cleanup_guaranteed") is False
        and type(value.get("outcomes")) is list
        and tuple(row.get("case") for row in value["outcomes"]) == EXPECTED
        and len(set(EXPECTED)) == 48
    )
    for row in value["outcomes"]:
        require(
            row.get("passed") is True
            and type(row.get("child")) is dict
            and row["child"].get("case") == row["case"]
            and row["child"].get("handlers_restored") is True
            and row["child"].get("active_guard_released") is True
            and row["child"].get("sentinel_exposed") is False
        )
    return {"status": "passed", "tests": 48, "failures": 0, "errors": 0, "skipped": 0}


def main():
    require(sys.platform == "linux" and os.geteuid() == 1000 and not sys.argv[1:])
    test = FIXTURE / "test_installed_signals.py"
    child = FIXTURE / "signal_child.py"
    launcher = ROOT / "ops/retirement/publisher_launcher.py"
    source = ROOT / "ops/retirement/installed_publisher.py"
    for path, expected in (
        (test, TEST_SHA),
        (child, CHILD_SHA),
        (launcher, LAUNCHER_SHA),
        (FIXTURE / "operator_scope.py", SCOPE_SHA),
        (ROOT / "ops/retirement/operator_scope.py", SCOPE_SHA),
        (FIXTURE / "original/test_installed_signals.py", ORIGINAL_TEST_SHA),
        (FIXTURE / "original/signal_child.py", ORIGINAL_CHILD_SHA),
    ):
        require(
            path.resolve(strict=True) == path
            and hashlib.sha256(path.read_bytes()).hexdigest() == expected
        )
    expected_source = hashlib.sha256(source.read_bytes()).hexdigest()
    # Same original per-case/ready/reap deadlines; the existing outer native
    # runner retains its 60-second overall cap. No case is deselected or skipped.
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            str(test),
            "--source",
            str(source),
            "--launcher",
            str(launcher),
            "--external-posix",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=55,
        close_fds=True,
    )
    print(
        json.dumps(
            {"publisher_signal_diagnostic": public_diagnostic(result, expected_source)}
        ),
        flush=True,
    )
    require(
        result.returncode == 0
        and not result.stderr
        and 0 < len(result.stdout) <= 65536
        and hashlib.sha256(source.read_bytes()).hexdigest() == expected_source
    )
    counts = validate(decode(result.stdout), expected_source)
    print(
        json.dumps(
            {
                "mode": "real_child_signals_private_and_RPC_IO_modeled",
                "source_sha256": expected_source,
                "launcher_sha256": LAUNCHER_SHA,
                "child_runner_sha256": CHILD_SHA,
                "case_ids_sha256": hashlib.sha256(
                    "\n".join(EXPECTED).encode()
                ).hexdigest(),
                "external_POSIX_cases": 6,
                "native_Docker_cleanup_proven": False,
            }
        ),
        flush=True,
    )
    print(json.dumps(counts), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
