"""Actual final-image Uvicorn/normal settings probe; no injected app or Runtime.

Only an owned native QA container may execute this program. Inputs are fresh
synthetic session/receipt metadata over stdin, never production configuration.
The web container receives no signing seed, checkpoint/recovery/backup DB role,
Docker socket or source overlay at /app. Recovery is a separate stopped process.
"""

import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from uuid import uuid4

ARGV = ["/usr/local/bin/uvicorn", "main:app", "--host", "127.0.0.1", "--port", "8000"]
ORIGIN = "https://workspace.fixture"
COOKIE = "__Host-aqua_session"
MODES = {"ready", "restored_closed", "receipt_purge"}
ENV = {
    "PATH": "/usr/local/bin:/usr/bin:/bin",
    "PYTHONPATH": "/app",
    "PYTHON_DOTENV_DISABLED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "APP_STORAGE_ENABLED": "true",
    "APP_DB_POOL_SIZE": "4",
    "APP_DB_MAX_WAITING": "8",
    "APP_DATABASE_URL": "host=/run/aqua-app-db port=5432 dbname=aqua_app user=aqua_app_runtime password=fixture-only sslmode=disable",
    "DATABASE_URL": "synthetic-workspace",
    "SESSION_SECRET": "fixture-workspace-secret-" * 3,
    "APP_ORIGIN": ORIGIN,
    "GOOGLE_CLIENT_ID": "fixture.apps.googleusercontent.com",
    "AUTH_ALLOWED_GOOGLE_SUBS": "workspace-A",
    "AUTH_ALLOWED_EMAILS": "a@gmail.com",
    "PASSWORD_AUTH_ENABLED": "true",
    "PRIVATE_DATA_EXPORT_ENABLED": "false",
    "PRIVATE_DATA_DELETE_ENABLED": "false",
    "WEB_CONCURRENCY": "1",
    "UVICORN_WORKERS": "1",
    "UVICORN_RELOAD": "false",
    "RETRIEVAL": "false",
    "LLM_FALLBACK": "false",
}

PHASES = {
    "input",
    "compiled_runtime",
    "mounts",
    "launch",
    "argv",
    "startup",
    "accepted_receipt",
    "restored_closed",
    "recovered_ready",
}
EXCEPTIONS = {
    "RuntimeError",
    "ValueError",
    "TypeError",
    "KeyError",
    "AssertionError",
    "OSError",
    "PermissionError",
    "FileNotFoundError",
    "TimeoutExpired",
    "JSONDecodeError",
    "ConnectionError",
    "ConnectionRefusedError",
    "TimeoutError",
    "HTTPException",
    "RemoteDisconnected",
    "KeyboardInterrupt",
    "Unclassified",
}
CATEGORIES = {
    "normal_runtime_probe_stderr_capacity",
    "normal_runtime_probe_inputs_invalid",
    "normal_runtime_probe_closed_listener_still_present",
    "normal_runtime_probe_complete_runtime_required",
    "normal_runtime_probe_ordinary_start_failed",
    "normal_runtime_probe_restored_server_unexpectedly_serving",
    "normal_runtime_probe_startup_failure_not_retirement_denial",
    "normal_runtime_probe_compiled_image_bytes_changed",
    "normal_runtime_probe_runtime_manifest_invalid",
    "normal_runtime_probe_owned_fixture_required",
    "normal_runtime_probe_cancelled",
    "normal_runtime_probe_legacy_grant_resurrected",
    "normal_runtime_probe_new_deletion_capability_open",
    "normal_runtime_probe_identity_invalid",
    "normal_runtime_probe_child_absence_unconfirmed",
    "normal_runtime_probe_readonly_mount_required",
    "normal_runtime_probe_start_deadline",
    "normal_runtime_probe_not_single_ordinary_uvicorn",
    "normal_runtime_probe_input_capacity",
    "normal_runtime_probe_port_collision",
    "normal_runtime_probe_synthetic_token_invalid",
    "normal_runtime_probe_closed_account_session_reopened",
    "normal_runtime_probe_response_capacity",
    "normal_runtime_probe_synthetic_CSRF_invalid",
    "normal_runtime_probe_accepted_receipt_lost",
    "normal_runtime_probe_new_deletion_allowed",
    "normal_runtime_probe_protected_inode_changed",
    "normal_runtime_probe_closed_exit_unproven",
    "normal_runtime_probe_closed_private_response_admitted",
    "normal_runtime_probe_flag_off_receipt_or_purge_unproven",
    "normal_runtime_probe_operator_authority_mounted",
}
ROUTES = {
    "health",
    "session",
    "deletion_receipt",
    "preferences",
    "deletion_create",
    "workspace_probe",
    "other",
}
_phase = "input"
_http_failure = None


def route_enum(method, path):
    known = {
        ("GET", "/api/health"): "health",
        ("GET", "/api/auth/me"): "session",
        ("GET", "/api/v1/me/preferences"): "preferences",
        ("POST", "/api/v1/me/data-deletions"): "deletion_create",
        ("GET", "/api/v1/chats"): "workspace_probe",
    }
    if method == "POST" and path.startswith("/api/v1/me/data-deletions/by-intent/"):
        return "deletion_receipt"
    return known.get((method, path), "other")


def validate_failure(value):
    if (
        type(value) is not dict
        or set(value) != {"status", "diagnostic"}
        or value["status"] != "failed"
    ):
        raise RuntimeError("normal_fixture_failure_shape_invalid")
    item = value["diagnostic"]
    if (
        type(item) is not dict
        or set(item) != {"phase", "exception_class", "category", "http_failure"}
        or type(item["phase"]) is not str
        or item["phase"] not in PHASES
        or type(item["exception_class"]) is not str
        or item["exception_class"] not in EXCEPTIONS
        or item["category"] is not None
        and (type(item["category"]) is not str or item["category"] not in CATEGORIES)
    ):
        raise RuntimeError("normal_fixture_failure_diagnostic_invalid")
    http = item["http_failure"]
    if http is not None and (
        type(http) is not dict
        or set(http) != {"route", "status", "bytes", "body_sha256"}
        or type(http["route"]) is not str
        or http["route"] not in ROUTES
        or type(http["status"]) is not int
        or not 100 <= http["status"] <= 599
        or type(http["bytes"]) is not int
        or not 0 <= http["bytes"] <= 65536
        or type(http["body_sha256"]) is not str
        or not re.fullmatch("[0-9a-f]{64}", http["body_sha256"])
    ):
        raise RuntimeError("normal_fixture_failure_HTTP_invalid")
    return item


def failure(error):
    name = type(error).__name__
    category = (
        error.args[0]
        if type(error) is RuntimeError
        and len(error.args) == 1
        and type(error.args[0]) is str
        and error.args[0] in CATEGORIES
        else None
    )
    value = {
        "status": "failed",
        "diagnostic": {
            "phase": _phase,
            "exception_class": name if name in EXCEPTIONS else "Unclassified",
            "category": category,
            "http_failure": _http_failure,
        },
    }
    validate_failure(value)
    return value


def request(method, path, body=None, headers=None):
    global _http_failure
    conn = http.client.HTTPConnection("127.0.0.1", 8000, timeout=2)
    raw = None if body is None else json.dumps(body).encode()
    try:
        conn.request(
            method,
            path,
            body=raw,
            headers={
                "Host": "workspace.fixture",
                "Origin": ORIGIN,
                **({"Content-Type": "application/json"} if body is not None else {}),
                **(headers or {}),
            },
        )
        response = conn.getresponse()
        value = response.read(65537)
        if len(value) > 65536:
            raise RuntimeError("normal_runtime_probe_response_capacity")
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            _http_failure = {
                "route": route_enum(method, path),
                "status": response.status,
                "bytes": len(value),
                "body_sha256": hashlib.sha256(value).hexdigest(),
            }
            raise
        return response.status, parsed, dict(response.getheaders())
    finally:
        conn.close()


def checked(value: dict) -> dict:
    fields = {
        "run",
        "mode",
        "runtime_files",
        "session_token",
        "csrf_token",
        "receipt_token",
        "intent_id",
        "job_id",
        "owner_id",
    }
    if (
        type(value) is not dict
        or set(value) != fields
        or value["mode"] not in MODES
        or not re.fullmatch(r"aqua-retirement-host-[a-f0-9]{24}", value["run"])
    ):
        raise RuntimeError("normal_runtime_probe_inputs_invalid")
    for field in ("session_token", "receipt_token"):
        if type(value[field]) is not str or not re.fullmatch(
            r"v2\.[A-Za-z0-9_-]{43}", value[field]
        ):
            raise RuntimeError("normal_runtime_probe_synthetic_token_invalid")
    if type(value["csrf_token"]) is not str or not re.fullmatch(
        r"[A-Za-z0-9_-]{43}", value["csrf_token"]
    ):
        raise RuntimeError("normal_runtime_probe_synthetic_CSRF_invalid")
    from uuid import UUID

    for field in ("intent_id", "job_id", "owner_id"):
        if type(value[field]) is not str or str(UUID(value[field])) != value[field]:
            raise RuntimeError("normal_runtime_probe_identity_invalid")
    files = value["runtime_files"]
    if type(files) is not dict or not 100 <= len(files) <= 300:
        raise RuntimeError("normal_runtime_probe_complete_runtime_required")
    for name, digest in files.items():
        path = Path(name)
        if (
            not name
            or path.is_absolute()
            or ".." in path.parts
            or path.suffix not in {".py", ".sql"}
            or type(digest) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", digest)
        ):
            raise RuntimeError("normal_runtime_probe_runtime_manifest_invalid")
    return value


def exact_runtime(files: dict, root=Path("/app")) -> str:
    observed = {
        str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in root.rglob("*")
        if path.is_file() and path.suffix in {".py", ".sql"}
    }
    if observed != files:
        raise RuntimeError("normal_runtime_probe_compiled_image_bytes_changed")
    return hashlib.sha256(
        json.dumps(observed, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def new_body(receipt: str) -> dict:
    proof = "v2." + "P" * 43
    if proof == receipt:
        proof = "v2." + "Q" * 43
    return {
        "intent_id": str(uuid4()),
        "scope": "chat_history_v1",
        "proof_token": proof,
        "receipt_token": receipt,
        "confirmation": "DELETE HISTORY",
    }


def same_inodes(expected):
    checkpoint = Path("/run/aqua-retirement/checkpoints.bin")
    mail = Path("/run/aqua-retirement/mail-worker.lock")
    if (
        checkpoint.stat().st_dev,
        checkpoint.stat().st_ino,
        mail.stat().st_dev,
        mail.stat().st_ino,
    ) != expected:
        raise RuntimeError("normal_runtime_probe_protected_inode_changed")


def stderr_read(child, buffer):
    while True:
        try:
            raw = os.read(child.stderr.fileno(), min(4096, 16385 - len(buffer)))
        except BlockingIOError:
            return
        if not raw:
            return
        buffer.extend(raw)
        if len(buffer) > 16384:
            raise RuntimeError("normal_runtime_probe_stderr_capacity")


def closed_startup(child, runtime_sha, inodes, diagnostic):
    code = child.wait(timeout=2)
    if (
        type(diagnostic) is not bytes
        or len(diagnostic) > 16384
        or not re.search(
            rb"(?:retirement\.interlock\.)?RetirementUnavailable: retirement_authority_unavailable(?:\r?\n|$)",
            diagnostic,
        )
    ):
        raise RuntimeError("normal_runtime_probe_startup_failure_not_retirement_denial")
    if code == 0 or Path(f"/proc/{child.pid}").exists():
        raise RuntimeError("normal_runtime_probe_closed_exit_unproven")
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.settimeout(0.2)
        if probe.connect_ex(("127.0.0.1", 8000)) == 0:
            raise RuntimeError("normal_runtime_probe_closed_listener_still_present")
    finally:
        probe.close()
    for path in ("/api/auth/me", "/api/v1/chats"):
        try:
            request("GET", path)
        except (OSError, http.client.HTTPException):
            pass
        else:
            raise RuntimeError("normal_runtime_probe_closed_private_response_admitted")
    return {
        "status": "passed",
        "checks": [
            "ordinary_final_image_flag_false_invalid_restored_history_exits_ASGI_startup_closed"
        ],
        "startup_mode": "startup_exited_closed",
        "actual_child_exit_code": code,
        "failure_category": "retirement_authority_unavailable",
        "stderr_sha256": hashlib.sha256(diagnostic).hexdigest(),
        "private_api_admitted": False,
        "runtime_sha256": runtime_sha,
        "web_processes": 0,
        "private_data_delete_enabled": False,
        "ordinary_runtime": True,
        "injected_runtime": False,
        "checkpoint_device": inodes[0],
        "checkpoint_inode": inodes[1],
        "mail_device": inodes[2],
        "mail_inode": inodes[3],
    }


def execute(value: dict) -> dict:
    global _phase
    value = checked(value)
    if (
        sys.platform != "linux"
        or os.geteuid() != 1000
        or os.environ.get("AQUA_RETIREMENT_NATIVE_FIXTURE") != "true"
    ):
        raise RuntimeError("normal_runtime_probe_owned_fixture_required")
    _phase = "compiled_runtime"
    runtime_sha = exact_runtime(value["runtime_files"])
    checkpoint = Path("/run/aqua-retirement/checkpoints.bin")
    mail = Path("/run/aqua-retirement/mail-worker.lock")
    _phase = "mounts"
    if not all(
        os.statvfs(path).f_flag & os.ST_RDONLY
        for path in (checkpoint, mail, checkpoint.parent)
    ):
        raise RuntimeError("normal_runtime_probe_readonly_mount_required")
    if any(
        Path(path).exists()
        for path in (
            "/run/aqua-retirement-host",
            "/run/aqua-retirement-backup",
            "/run/aqua-retirement-recovery",
            "/var/run/docker.sock",
        )
    ):
        raise RuntimeError("normal_runtime_probe_operator_authority_mounted")
    expected_before = (
        checkpoint.stat().st_dev,
        checkpoint.stat().st_ino,
        mail.stat().st_dev,
        mail.stat().st_ino,
    )
    previous = {}
    cleaning = False
    child = None

    def cancel(number, frame):
        if not cleaning:
            raise RuntimeError("normal_runtime_probe_cancelled")

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
        previous[number] = signal.getsignal(number)
        signal.signal(number, cancel)
    signal.alarm(40)
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            probe.settimeout(0.2)
            if probe.connect_ex(("127.0.0.1", 8000)) == 0:
                raise RuntimeError("normal_runtime_probe_port_collision")
        finally:
            probe.close()
        _phase = "launch"
        child = subprocess.Popen(
            ARGV,
            cwd="/app",
            env=ENV,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            close_fds=True,
        )
        os.set_blocking(child.stderr.fileno(), False)
        diagnostic = bytearray()
        _phase = "argv"
        actual = Path(f"/proc/{child.pid}/cmdline").read_bytes().split(b"\0")[:-1]
        if (
            actual
            not in (
                [argument.encode() for argument in ARGV],
                [sys.executable.encode(), *[argument.encode() for argument in ARGV]],
            )
            or Path(f"/proc/{child.pid}/task/{child.pid}/children").read_text().strip()
        ):
            raise RuntimeError("normal_runtime_probe_not_single_ordinary_uvicorn")
        _phase = "startup"
        until = time.monotonic() + 12
        while True:
            stderr_read(child, diagnostic)
            if child.poll() is not None:
                stderr_read(child, diagnostic)
                if value["mode"] == "restored_closed":
                    _phase = "restored_closed"
                    same_inodes(expected_before)
                    return closed_startup(
                        child, runtime_sha, expected_before, bytes(diagnostic)
                    )
                raise RuntimeError("normal_runtime_probe_ordinary_start_failed")
            try:
                status, body, _ = request("GET", "/api/health")
                if status == 200:
                    break
            except (OSError, http.client.HTTPException):
                pass
            if time.monotonic() > until:
                raise RuntimeError("normal_runtime_probe_start_deadline")
            time.sleep(0.05)
        _phase = (
            "accepted_receipt"
            if value["mode"] == "receipt_purge"
            else "recovered_ready"
        )
        headers = {
            "Cookie": COOKIE + "=" + value["session_token"],
            "X-CSRF-Token": value["csrf_token"],
        }
        checks = [
            "normal_settings_load_and_Runtime_create_final_compiled_image_single_uvicorn_flag_false"
        ]
        if value["mode"] == "restored_closed":
            raise RuntimeError(
                "normal_runtime_probe_restored_server_unexpectedly_serving"
            )
        else:
            status, body, _ = request("GET", "/api/auth/me", headers=headers)
            if value["mode"] == "receipt_purge":
                if status != 401:
                    raise RuntimeError(
                        "normal_runtime_probe_closed_account_session_reopened"
                    )
                status, body, _ = request(
                    "POST",
                    "/api/v1/me/data-deletions/by-intent/" + value["intent_id"],
                    {},
                    {**headers, "X-Aqua-Deletion-Receipt": value["receipt_token"]},
                )
                until = time.monotonic() + 12
                reads = 1
                while (
                    status == 200
                    and body.get("job", {}).get("cleanup_complete") is False
                    and time.monotonic() < until
                    and reads < 18
                ):
                    if body["job"].get("accepted") is not True:
                        raise RuntimeError("normal_runtime_probe_accepted_receipt_lost")
                    time.sleep(0.5)
                    reads += 1
                    status, body, _ = request(
                        "POST",
                        "/api/v1/me/data-deletions/by-intent/" + value["intent_id"],
                        {},
                        {**headers, "X-Aqua-Deletion-Receipt": value["receipt_token"]},
                    )
                job = body.get("job", {})
                if (
                    status != 200
                    or body.get("user_id") != value["owner_id"]
                    or job.get("intent_id") != value["intent_id"]
                    or job.get("id") != value["job_id"]
                    or job.get("accepted") is not True
                    or job.get("cleanup_complete") is not True
                ):
                    raise RuntimeError(
                        "normal_runtime_probe_flag_off_receipt_or_purge_unproven"
                    )
                checks.append(
                    "accepted_account_receipt_and_actual_background_purge_continue_flag_false"
                )
            else:
                if (
                    status != 200
                    or body.get("can_query") is not False
                    or body.get("user", {}).get("id") != value["owner_id"]
                ):
                    raise RuntimeError("normal_runtime_probe_legacy_grant_resurrected")
                status, body, _ = request(
                    "GET", "/api/v1/me/preferences", headers=headers
                )
                if (
                    status != 200
                    or body.get("capabilities", {}).get("private_data_delete")
                    is not False
                ):
                    raise RuntimeError(
                        "normal_runtime_probe_new_deletion_capability_open"
                    )
                body = new_body(value["receipt_token"])
                status, _, _ = request(
                    "POST", "/api/v1/me/data-deletions", body, headers
                )
                if status != 503:
                    raise RuntimeError("normal_runtime_probe_new_deletion_allowed")
                checks.append(
                    "new_UUID_legacy_grant_denied_and_new_deletion_creation_closed"
                )
        same_inodes(expected_before)
        return {
            "status": "passed",
            "checks": checks,
            "runtime_sha256": runtime_sha,
            "web_processes": 1,
            "private_data_delete_enabled": False,
            "ordinary_runtime": True,
            "injected_runtime": False,
            "checkpoint_device": expected_before[0],
            "checkpoint_inode": expected_before[1],
            "mail_device": expected_before[2],
            "mail_inode": expected_before[3],
        }
    finally:
        cleaning = True
        signal.alarm(0)
        try:
            if child is not None:
                if child.poll() is None:
                    child.terminate()
                    try:
                        child.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        child.kill()
                        child.wait(timeout=3)
                if child.stderr is not None:
                    child.stderr.close()
                if Path(f"/proc/{child.pid}").exists():
                    raise RuntimeError("normal_runtime_probe_child_absence_unconfirmed")
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)


def main() -> None:
    global _phase, _http_failure
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {"status": "prepared_only", "private_reads": 0, "processes_started": 0}
            )
        )
        return
    _phase, _http_failure = "input", None
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise RuntimeError("normal_runtime_probe_input_capacity")
        # No input token, proof, request body or session metadata is printed.
        print(json.dumps(execute(json.loads(raw)), sort_keys=True))
    except (Exception, KeyboardInterrupt) as error:
        print(json.dumps(failure(error), sort_keys=True), flush=True)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
