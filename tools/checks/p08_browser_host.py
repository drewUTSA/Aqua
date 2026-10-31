"""P08 reuses tested resource ownership with a narrower fixed worker budget."""

import json
import secrets
import signal
import subprocess

from p05_browser_host import close_worker, timeout_signal
from p05_browser_protocol import MAX_LINE, emit, fixture_schema, message
from p05_browser_docker import ROOT
from p05_browser_resources import Resources

MAX_OPERATIONS = 200
MAX_SECONDS = 180


def host(origin: str, image: str) -> int:
    """One network-none fixture, fixed worker path, no production configuration."""
    name = "aqua-p05-browser-" + secrets.token_hex(12)
    schema = fixture_schema(ROOT)
    resources, child, final_id = Resources(name), None, "finish"
    report = {
        "run": name,
        "status": "failed",
        "network": "none",
        "schema_version": schema,
        "max_operations": MAX_OPERATIONS,
        "max_seconds": MAX_SECONDS,
        "real_data_accessed": False,
        "provider_calls": 0,
        "presentation_fixture": True,
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
                "/checks/tools/checks/p08_browser_backend.py",
                "--worker",
                "--origin",
                origin,
                "--image",
                image,
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
            ready.get("kind") != "ready"
            or ready.get("schema_version") != schema
            or ready.get("workspace_analysis_fixture") is not True
        ):
            if ready.get("kind") == "error":
                report["worker_error"] = {
                    key: ready.get(key) for key in ("category", "stage", "module")
                }
            raise RuntimeError("fixture_worker_not_ready")
        emit(ready)
        for _ in range(MAX_OPERATIONS):
            item = message()
            if item is None or item.get("kind") == "finish":
                final_id = item["id"] if item else "finish"
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
            report.update(status="failed", worker_exit="unconfirmed_or_nonzero")
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
