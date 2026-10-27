"""Network-none runtime probe: health logs remain and private URLs do not leak.

Pipe this program to `python -` inside the exact candidate runtime image. The
only HTTP peer is that container's loopback; no storage/provider is configured.
"""

import json
import signal
import subprocess
import sys
import time

import httpx

child = subprocess.Popen(
    [
        sys.executable,
        "-m",
        "uvicorn",
        "main:app",
        "--host",
        "127.0.0.1",
        "--port",
        "18080",
        "--no-use-colors",
    ],
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
)
try:
    with httpx.Client(
        base_url="http://127.0.0.1:18080", timeout=2, trust_env=False
    ) as client:
        for _ in range(100):
            try:
                assert client.get("/api/health").status_code == 200
                break
            except httpx.ConnectError:
                time.sleep(0.1)
        else:
            raise AssertionError("isolated_runtime_not_ready")
        canary = "PRIVATE_WORKSPACE_RUNTIME_CANARY"
        assert client.get("/api/v1/chats", params={"search": canary}).status_code in {
            401,
            422,
            503,
        }
        assert client.post(
            "/api/v1/chats/search", json={"search": canary}
        ).status_code in {401, 403, 503}
        prefix = "/api/v1/analysis-requests/00000000-0000-4000-8000-000000000001"
        for suffix in ("", "/events"):
            assert client.get(
                prefix + suffix, params={"cursor": canary}
            ).status_code in {401, 403, 422, 503}
        assert client.post(prefix + "/cancel", json={}).status_code in {401, 403, 503}
finally:
    child.terminate()
    try:
        output, _ = child.communicate(timeout=5)
    except subprocess.TimeoutExpired:
        child.kill()
        child.communicate(timeout=2)
        raise AssertionError("isolated_runtime_shutdown_failed") from None
assert child.returncode in {0, -signal.SIGTERM}, "isolated_runtime_exit_failed"
assert (
    b"Application shutdown complete" in output
), "isolated_runtime_shutdown_unconfirmed"
assert len(output) <= 32768, "isolated_runtime_log_bound_failed"
assert b"GET /api/health HTTP/1.1" in output, "ordinary_access_log_missing"
assert b"PRIVATE_WORKSPACE_RUNTIME_CANARY" not in output, "private_access_log_leak"
assert b"/api/v1/chats" not in output, "workspace_access_log_not_suppressed"
assert b"/api/v1/analysis-requests" not in output, "analysis_access_log_not_suppressed"
print(
    json.dumps(
        {
            "status": "passed",
            "network": "none",
            "ordinary_access_log": "retained",
            "private_workspace_access_log": "suppressed",
            "real_data_accessed": False,
        }
    )
)
