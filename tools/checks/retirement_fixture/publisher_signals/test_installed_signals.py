"""Focused real-child signals; no Docker, private reads, external services or builds."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

CASES = (
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
)
FOCUSED_BASELINE = (
    "normal_cleanup_TERM",
    "normal_cleanup_repeat_INT",
    "normal_rm_repeat_TERM",
    "direct_normal_cleanup_TERM",
    "direct_normal_cleanup_repeat_INT",
    "direct_start_INT",
    "direct_nonmain_thread",
    "direct_before_launch_INT",
)


def check(full_case, result):
    direct = full_case.startswith("direct_")
    case = full_case[len("direct_") :] if direct else full_case
    case = case[len("external_") :] if case.startswith("external_") else case
    assert result["handlers_restored"] is True, "prior_handlers_not_restored"
    assert result["active_guard_released"] is True, "active_guard_latched"
    if case.endswith(("TERM", "INT")) or case == "print_signal":
        assert result["signal_deliveries"] >= 1, "requested_signal_not_observed"
    assert result["sentinel_exposed"] is False, "unredacted_entrypoint_output"
    assert (
        result.get("exception_trace_sentinel_exposed", False) is False
    ), "unredacted_exception_context"
    if direct:
        assert result["entrypoint_output"] == "", "direct_execute_printed_output"
        if case in {"idle", "checked", "busy"}:
            assert result["returned_status"] == case and result["exit_code"] == 0
            assert result["escaped_type"] is None
        else:
            assert result["exit_code"] == 1 and result["escaped_type"] == "Unavailable"
            assert result["fixed_unavailable"] is True
    else:
        output = json.loads(result["entrypoint_output"])
        if case == "prepared":
            assert output == {
                "status": "prepared_only",
                "private_reads": 0,
                "Docker_actions": 0,
            }
            assert (
                result["private_reads"]
                == result["source_checks"]
                == result["docker_model_calls"]
                == result["signal_registrations"]
                == 0
            )
            assert result["exit_code"] == 0 and result["escaped_type"] is None
            return
        if case in {"idle", "checked", "busy"}:
            assert output == {"status": case}
            assert result["exit_code"] == 0 and result["escaped_type"] is None
        else:
            assert output == {
                "status": "unavailable"
            }, "fixed_unavailable_output_missing"
            assert result["exit_code"] == 1 and result["escaped_type"] == "SystemExit"
    if case in {"invalid_pin", "registration_failure", "nonmain_thread"}:
        assert result["private_reads"] == result["docker_model_calls"] == 0
    if case == "reentrant":
        assert result["private_reads"] == 1 and result["docker_model_calls"] == 0
    if case.startswith("before_launch_"):
        assert result["private_reads"] == result["source_checks"] == 1
        assert result["docker_model_calls"] == 0
    if case.startswith(
        ("create_", "start_", "repeat_", "normal_cleanup_", "normal_rm_")
    ) or case in {"idle", "checked"}:
        assert (
            result["cleanup_entered"] and result["cleanup_completed"]
        ), "actual_cleanup_not_completed"
        assert result["removed_exact_id"] and result["ownership_metadata_checked"]
        assert result["singleton_exited"] is True
        assert (
            result["work_budget_seconds"] == 50 and result["total_budget_seconds"] == 55
        )
        if case.startswith("create_failure_"):
            assert result["create_returned_identifier"] is False
        else:
            assert result["create_returned_identifier"] is True
    if "repeat" in case:
        assert result["signal_deliveries"] >= 2, "repeat_signal_not_observed"
    if case == "cleanup_false":
        assert result["cleanup_entered"] and result["cleanup_uncertain"]
        assert (
            result["removed_exact_id"] is False and result["cleanup_completed"] is False
        )
        assert result["singleton_exited"] is True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--launcher", type=Path, required=True)
    parser.add_argument("--external-posix", action="store_true")
    parser.add_argument("--focused-baseline", action="store_true")
    args = parser.parse_args()
    source = args.source.resolve(strict=True)
    launcher = args.launcher.resolve(strict=True)
    assert (
        hashlib.sha256(launcher.read_bytes()).hexdigest()
        == "37452a4aee1a63ec1f2cce9fcae8be3de2b6d015ef2d0e824e4dfe4ab6b8fe66"
    )
    child = Path(__file__).with_name("signal_child.py")
    cases = list(FOCUSED_BASELINE if args.focused_baseline else CASES)
    external = {"status": "not_run", "reason": "not_requested", "count": 0}
    if args.external_posix:
        if os.name != "posix":
            external["reason"] = "Windows_os_kill_does_not_model_POSIX_signal_delivery"
        else:
            cases += [
                "external_start_TERM",
                "external_start_INT",
                "external_normal_cleanup_TERM",
                "external_normal_cleanup_INT",
                "direct_external_normal_cleanup_TERM",
                "direct_external_normal_cleanup_INT",
            ]
            external = {"status": "requested", "count": 6}
    outcomes = []
    for case in cases:
        command = [
            sys.executable,
            "-I",
            "-B",
            str(child),
            "--source",
            str(source),
            "--launcher",
            str(launcher),
            "--case",
            case,
        ]
        began = time.monotonic()
        raw, error, code = "", "", None
        try:
            if "external_" in case:
                # The child waits at the actual launch start path for this signal.
                with subprocess.Popen(
                    command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
                ) as process:
                    try:
                        with selectors.DefaultSelector() as selector:
                            selector.register(process.stdout, selectors.EVENT_READ)
                            assert selector.select(
                                timeout=4
                            ), "child_signal_readiness_deadline"
                            ready = process.stdout.readline()
                        assert json.loads(ready)["event"] == "signal_point"
                        os.kill(
                            process.pid,
                            signal.SIGTERM if case.endswith("TERM") else signal.SIGINT,
                        )
                        tail, error = process.communicate(
                            timeout=max(0.1, 10 - (time.monotonic() - began))
                        )
                        raw, code = ready + tail, process.returncode
                    finally:
                        if process.poll() is None:
                            process.kill()
                            process.communicate(timeout=2)
            else:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                raw, error, code = (
                    completed.stdout,
                    completed.stderr,
                    completed.returncode,
                )
            assert len(raw) <= 16384 and len(error) <= 16384, "child_output_bound"
            records = [json.loads(line) for line in raw.splitlines()]
            results = [record for record in records if "entrypoint_output" in record]
            assert len(results) == 1, "child_result_missing_after_signal"
            result = results[0]
            assert error == "", "unexpected_child_stderr"
            assert code == result["exit_code"], "child_exit_mismatch"
            check(case, result)
            outcomes.append(
                {
                    "case": case,
                    "passed": True,
                    "child": result,
                    "elapsed_seconds": round(time.monotonic() - began, 4),
                }
            )
        except (
            AssertionError,
            ValueError,
            KeyError,
            subprocess.TimeoutExpired,
        ) as failure:
            outcomes.append(
                {
                    "case": case,
                    "passed": False,
                    "failure_category": (
                        str(failure)
                        if isinstance(failure, AssertionError)
                        else type(failure).__name__
                    ),
                    "child_exit_code": code,
                    "child_stdout_sha256": hashlib.sha256(raw.encode()).hexdigest(),
                    "child_stderr_sha256": hashlib.sha256(error.encode()).hexdigest(),
                    "child_stdout": raw if len(raw) <= 16384 else None,
                    "child_stderr_bytes": len(error),
                    "elapsed_seconds": round(time.monotonic() - began, 4),
                }
            )
    if external["status"] == "requested":
        external["status"] = (
            "passed"
            if all(row["passed"] for row in outcomes if "external_" in row["case"])
            else "failed"
        )
    report = {
        "mode": "actual_child_signals_actual_launch_Docker_ids_owned_clean_only_RPC_and_private_IO_modeled",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "launcher_sha256": hashlib.sha256(launcher.read_bytes()).hexdigest(),
        "child_runner_sha256": hashlib.sha256(child.read_bytes()).hexdigest(),
        "tests": len(outcomes),
        "passed": sum(row["passed"] for row in outcomes),
        "failed": sum(not row["passed"] for row in outcomes),
        "external_posix_delivery": external,
        "child_timeout_seconds": 10,
        "native_Docker_private_files_services_network": False,
        "actual_Docker_clean_exercised": True,
        "native_cleanup_guaranteed": False,
        "focused_baseline": args.focused_baseline,
        "outcomes": outcomes,
    }
    print(json.dumps(report, sort_keys=True, indent=2))
    raise SystemExit(0 if report["failed"] == 0 else 1)


if __name__ == "__main__":
    main()
