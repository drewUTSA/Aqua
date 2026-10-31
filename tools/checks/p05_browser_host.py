"""Bound bridge lifetime and guarantee owned-resource cleanup on every exit."""

import json
import re
import secrets
import signal
import subprocess
from typing import Any

from p05_browser_protocol import MAX_LINE, MAX_SECONDS, emit, message, request_limit
from p05_browser_resources import Resources


def timeout_signal(signum: int, frame: Any) -> None:
    raise TimeoutError("fixture_deadline")


def close_worker(child: subprocess.Popen[bytes]) -> bool:
    """Pipe failures must never prevent Docker resource cleanup."""
    if child.stdin is not None:
        try:
            child.stdin.close()
        except OSError:
            pass
    for action in (None, child.terminate, child.kill):
        try:
            if action is not None:
                action()
            return child.wait(timeout=5) == 0
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def host(
    origin: str,
    image: str,
    workspace_analysis: bool = False,
    *,
    account_security_fixture: bool = False,
) -> int:
    """Bound all operations/lifetime; lifecycle mode explicitly allows 400."""
    if type(account_security_fixture) is not bool:
        raise ValueError("fixture_security_mode_invalid")
    if account_security_fixture:
        from p10b_browser_fixture import MAX_REQUESTS, secure_origin

        secure_origin(origin)
        if workspace_analysis is not True or not re.fullmatch(
            r"sha256:[a-f0-9]{64}", image
        ):
            raise ValueError("fixture_security_mode_invalid")
        operations = MAX_REQUESTS
    else:
        operations = request_limit(workspace_analysis)
    name = "aqua-p05-browser-" + secrets.token_hex(12)
    resources = Resources(name)
    child: subprocess.Popen[bytes] | None = None
    final_id: str | int = "finish"
    report: dict[str, Any] = {
        "run": name,
        "status": "failed",
        "network": "none",
        "database_transport": "private_unix_socket",
        "schema_version": 6,
        "max_operations": operations,
        "account_security_fixture": account_security_fixture,
        "real_data_accessed": False,
        "provider_calls": 0,
        "workspace_analysis_fixture": workspace_analysis,
    }
    signal.signal(signal.SIGALRM, timeout_signal)
    signal.signal(signal.SIGTERM, timeout_signal)
    signal.signal(signal.SIGHUP, timeout_signal)
    signal.alarm(MAX_SECONDS)
    try:
        runner = resources.provision(image, report)
        report["step"] = "worker_start"
        child = subprocess.Popen(
            [
                "/usr/bin/docker",
                "--host=unix:///var/run/docker.sock",
                "exec",
                "-i",
                runner,
                "python",
                "-B",
                "-u",
                (
                    "/checks/tools/checks/p10b_browser_backend.py"
                    if account_security_fixture
                    else "/checks/tools/checks/p05_browser_backend.py"
                ),
                "--worker",
                "--origin",
                origin,
                *(
                    ["--image", image]
                    if account_security_fixture
                    else ["--workspace-analysis"] if workspace_analysis else []
                ),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env={
                "PATH": "/usr/bin:/bin",
                "HOME": "/proc/self/fd",
                "DOCKER_CONFIG": "/proc/self/fd",
            },
        )
        assert child.stdout is not None and child.stdin is not None
        ready = json.loads(child.stdout.readline(MAX_LINE + 1))
        if (
            account_security_fixture
            and ready.get("account_security_fixture") is not True
        ):
            raise RuntimeError("fixture_security_worker_not_ready")
        if ready.get("kind") != "ready" or ready.get("schema_version") != 6:
            if ready.get("kind") == "error":
                report["worker_error"] = {
                    key: ready.get(key) for key in ("category", "stage", "module")
                }
            raise RuntimeError("fixture_worker_not_ready")
        emit(ready)
        for _ in range(operations):
            item = message()
            if item is None or item.get("kind") == "finish":
                final_id = item["id"] if item is not None else "finish"
                report["status"] = "passed"
                break
            child.stdin.write(json.dumps(item).encode() + b"\n")
            child.stdin.flush()
            raw = child.stdout.readline(MAX_LINE + 1)
            if not raw or len(raw) > MAX_LINE or not raw.endswith(b"\n"):
                raise RuntimeError("fixture_worker_protocol_failed")
            emit(json.loads(raw))
        else:
            raise RuntimeError("fixture_message_count_limit")
    except (
        ValueError,
        TypeError,
        RuntimeError,
        TimeoutError,
        OSError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
    ):
        report["failure"] = "fixture_operation_failed_details_redacted"
    finally:
        signal.alarm(0)
        if child is not None and not close_worker(child):
            report["status"] = "failed"
            report["worker_exit"] = "unconfirmed_or_nonzero"
        remaining = resources.cleanup()
        report["cleanup"] = "failed" if remaining else "removed_and_absence_confirmed"
        report["remaining_ids"] = remaining
        emit(
            {
                "id": final_id,
                "kind": "finished",
                "status": (
                    "passed"
                    if report["status"] == "passed" and not remaining
                    else "failed"
                ),
                "report": report,
            }
        )
    return int(report["status"] != "passed" or bool(report["remaining_ids"]))
