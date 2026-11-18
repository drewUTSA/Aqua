"""Bound bridge lifetime and guarantee owned-resource cleanup on every exit."""

import json
import re
import secrets
import signal
import subprocess
from typing import Any

from p05_browser_protocol import (
    MAX_LINE,
    MAX_SECONDS,
    emit,
    fixture_schema,
    message,
    origin_value,
    request_limit,
)
from p05_browser_docker import ROOT
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
    account_identity_fixture: bool = False,
    personal_export_fixture: bool = False,
    personal_deletion_fixture: bool = False,
    bank_demo_fixture: bool = False,
    notes_fixture: bool = False,
) -> int:
    """Bound all operations/lifetime; lifecycle mode explicitly allows 400."""
    if (
        type(account_security_fixture) is not bool
        or type(account_identity_fixture) is not bool
        or type(personal_export_fixture) is not bool
        or type(personal_deletion_fixture) is not bool
        or type(bank_demo_fixture) is not bool
        or type(notes_fixture) is not bool
    ):
        raise ValueError("fixture_security_mode_invalid")
    if notes_fixture and (
        workspace_analysis is not False
        or account_security_fixture
        or account_identity_fixture
        or personal_export_fixture
        or personal_deletion_fixture
        or bank_demo_fixture
        or type(image) is not str
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)
    ):
        raise ValueError("fixture_notes_mode_invalid")
    if notes_fixture:
        origin_value(origin)
    if bank_demo_fixture and (
        workspace_analysis is not False
        or account_security_fixture
        or account_identity_fixture
        or personal_export_fixture
        or personal_deletion_fixture
        or notes_fixture
        or type(image) is not str
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)
    ):
        raise ValueError("fixture_bank_demo_mode_invalid")
    if bank_demo_fixture:
        origin_value(origin)
    schema = fixture_schema(ROOT)
    if type(schema) is not int or schema != 10:
        raise ValueError("fixture_schema10_required")
    if account_identity_fixture and (not account_security_fixture):
        raise ValueError("fixture_identity_mode_invalid")
    if personal_export_fixture and (
        not account_identity_fixture or not account_security_fixture
    ):
        raise ValueError("fixture_export_mode_invalid")
    if personal_deletion_fixture and (
        schema != 10
        or not account_identity_fixture
        or not account_security_fixture
        or personal_export_fixture
        or workspace_analysis is not True
    ):
        raise ValueError("fixture_deletion_mode_invalid")
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
    if personal_deletion_fixture:
        from p11b_browser_resources import DeletionResources

        resources = DeletionResources(name)
    else:
        resources = Resources(name)
    child: subprocess.Popen[bytes] | None = None
    final_id: str | int = "finish"
    report: dict[str, Any] = {
        "run": name,
        "status": "failed",
        "network": "none",
        "database_transport": "private_unix_socket",
        "schema_version": schema,
        "max_operations": operations,
        "account_security_fixture": account_security_fixture,
        "account_identity_fixture": account_identity_fixture,
        "personal_export_fixture": personal_export_fixture,
        "personal_deletion_fixture": personal_deletion_fixture,
        "real_data_accessed": False,
        "provider_calls": 0,
        "workspace_analysis_fixture": workspace_analysis,
        **({"notes_fixture": True} if notes_fixture else {}),
        **(
            {"bank_demo_fixture": True, "bank_demo_persona": "teller"}
            if bank_demo_fixture
            else {}
        ),
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
                    "/checks/tools/checks/context_notes_browser_backend.py"
                    if notes_fixture
                    else (
                        "/checks/tools/checks/bank_demo_browser_backend.py"
                        if bank_demo_fixture
                        else None
                    )
                )
                or (
                    "/checks/tools/checks/p11b_browser_backend.py"
                    if personal_deletion_fixture
                    else (
                        "/checks/tools/checks/p11a_browser_backend.py"
                        if personal_export_fixture
                        else (
                            "/checks/tools/checks/p10c_browser_backend.py"
                            if account_identity_fixture
                            else (
                                "/checks/tools/checks/p10b_browser_backend.py"
                                if account_security_fixture
                                else "/checks/tools/checks/p05_browser_backend.py"
                            )
                        )
                    )
                ),
                "--worker",
                "--origin",
                origin,
                *(
                    ["--image", image]
                    if account_security_fixture or bank_demo_fixture or notes_fixture
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
        if type(ready) is not dict:
            raise RuntimeError("fixture_worker_not_ready")
        if ready.get("notes_fixture", False) is not notes_fixture:
            raise RuntimeError("fixture_notes_worker_not_ready")
        if notes_fixture and (
            type(ready.get("schema_version")) is not int
            or ready["schema_version"] != 10
            or ready.get("origin") != origin
            or ready.get("workspace_analysis_fixture") is not False
            or type(ready.get("capabilities")) is not dict
            or ready["capabilities"].get("workspace_analysis") is not False
            or type(ready.get("max_requests")) is not int
            or ready["max_requests"] != 256
            or type(ready.get("max_seconds")) is not int
            or ready["max_seconds"] != 300
            or type(ready.get("body_bytes_max")) is not int
            or ready["body_bytes_max"] != 16384
            or type(ready.get("dataset_grants")) is not int
            or ready["dataset_grants"] != 0
        ):
            raise RuntimeError("fixture_notes_worker_not_ready")
        if ready.get("bank_demo_fixture", False) is not bank_demo_fixture or (
            bank_demo_fixture and ready.get("bank_demo_persona") != "teller"
        ):
            raise RuntimeError("fixture_bank_demo_worker_not_ready")
        if (
            ready.get("personal_deletion_fixture", False)
            is not personal_deletion_fixture
        ):
            raise RuntimeError("fixture_deletion_worker_not_ready")
        if ready.get("personal_export_fixture", False) is not personal_export_fixture:
            raise RuntimeError("fixture_export_worker_not_ready")
        if ready.get("account_identity_fixture", False) is not account_identity_fixture:
            raise RuntimeError("fixture_identity_worker_not_ready")
        if (
            account_security_fixture
            and ready.get("account_security_fixture") is not True
        ):
            raise RuntimeError("fixture_security_worker_not_ready")
        if ready.get("kind") != "ready" or ready.get("schema_version") != schema:
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
