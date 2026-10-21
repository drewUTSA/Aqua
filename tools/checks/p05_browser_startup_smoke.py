"""Prove readiness ignores the pinned image's temporary initialization server.

Uses one disposable, network-none PostgreSQL with synthetic data in tmpfs.
An explicit, bounded init barrier makes the old readiness race observable.
"""

import hashlib
import json
import secrets
import subprocess
import time

from p05_browser_docker import create, docker
from p05_browser_protocol import POSTGRES
from p05_browser_resources import Resources, wait_for_postgres


def check() -> dict:
    name = "aqua-p05-browser-" + secrets.token_hex(12)
    owned = Resources(name)
    report = {
        "purpose": "p05_temporary_postgres_readiness_regression",
        "status": "failed",
    }
    # This fixed, sourced init script holds the temporary server until the
    # observer releases it. A timer-only delay could expire while CI is paused.
    # Its own 60-second deadline also bounds it if the observer is interrupted.
    # No user input or real SQL enters this disposable-container-only script.
    entrypoint = (
        "printf '%s\\n' "
        "'aqua_init_deadline=$((SECONDS + 60))' "
        "'while [[ ! -f /tmp/aqua-p05-init-release ]]; do' "
        "'  if ((SECONDS >= aqua_init_deadline)); then return 1; fi' "
        "'  sleep 0.1' "
        "'done' > /docker-entrypoint-initdb.d/001-release.sh; "
        "exec /usr/local/bin/docker-entrypoint.sh postgres -c listen_addresses= "
        "-c unix_socket_directories=/var/run/postgresql,/run/aqua-app-db"
    )
    try:
        report["postgres_image"] = (
            docker("image", "inspect", POSTGRES, "--format", "{{.Id}}").decode().strip()
        )
        owned.preparing("container", name + "-pg")
        pg = create(
            name + "-pg",
            POSTGRES,
            "--user=999:999",
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=268435456,uid=999,gid=999,mode=0700",
            "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
            "--tmpfs=/run/aqua-app-db:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
            "--tmpfs=/docker-entrypoint-initdb.d:rw,nosuid,nodev,size=1048576,uid=999,gid=999",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=16777216",
            "-e",
            "POSTGRES_HOST_AUTH_METHOD=trust",
            "--entrypoint=/bin/bash",
            command=("-c", entrypoint),
        )
        owned.uncertain.discard(name + "-pg")
        docker("start", pg)
        deadline = time.monotonic() + 30
        while True:
            try:
                # Reproduce the old gate exactly, while the init script holds
                # the temporary server open. It must not authorize app setup.
                docker("exec", pg, "pg_isready", "-U", "postgres", timeout=5)
                break
            except RuntimeError:
                if time.monotonic() >= deadline:
                    raise RuntimeError("startup_regression_probe_timeout") from None
                time.sleep(0.1)
        assert (
            docker("exec", pg, "cat", "/proc/1/comm").strip() == b"bash"
        ), "temporary_server_not_observed"
        report["old_gate_accepts_temporary_server"] = True
        docker("exec", pg, "touch", "/tmp/aqua-p05-init-release")
        report["initialization_release_barrier_seconds"] = 60
        script = docker("exec", pg, "cat", "/usr/local/bin/docker-entrypoint.sh")
        report["pinned_entrypoint_sha256"] = hashlib.sha256(script).hexdigest()
        wait_for_postgres(pg)
        assert docker("exec", pg, "cat", "/proc/1/comm").strip() == b"postgres"
        result = docker(
            "exec",
            pg,
            "psql",
            "-XAt",
            "-h",
            "/run/aqua-app-db",
            "-U",
            "postgres",
            "-c",
            "SELECT current_setting('listen_addresses')='', 1",
        )
        assert result.strip() == b"t|1", "final_socket_server_unavailable"
        report.update(
            status="passed",
            final_process_gate=True,
            final_socket_query=True,
            network="none",
            tcp_listener=False,
        )
    except (
        AssertionError,
        RuntimeError,
        OSError,
        TimeoutError,
        subprocess.TimeoutExpired,
    ):
        report["failure"] = "startup_regression_failed_details_redacted"
    finally:
        remaining = owned.cleanup()
        report["cleanup"] = "failed" if remaining else "removed_and_absence_confirmed"
        report["remaining_ids"] = remaining
        if remaining:
            report["status"] = "failed"
    return report


if __name__ == "__main__":
    result = check()
    print(json.dumps(result))
    raise SystemExit(result["status"] != "passed")
