"""Run the same bounded proxy security checks locally and in CI, without ingress."""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time

from run_backend import create, docker

ROOT = Path(__file__).resolve().parents[2]
NGINX = "nginx@sha256:970364228b1e4f932abc22d321932816782cca8a20b85a77552a7cfe9acfb3b5"


def run(
    config: Path,
    output: Path,
    baseline: bool = False,
    nginx_image: str = NGINX,
    *,
    identity_actions: bool = False,
) -> int:
    """No host mounts/ports/sockets; only the synthetic upstream shares the netns."""
    if baseline and identity_actions:
        raise ValueError("identity_actions_have_no_unsafe_baseline")
    probe_name = "p10c_proxy_probe.py" if identity_actions else "proxy_probe.py"
    name = "aqua-proxy-check-" + secrets.token_hex(12)
    containers = []
    report = {"name": name, "network": "none", "status": "failed", "cleanup": "pending"}
    if identity_actions:
        report["exercise_kind"] = "p10c_identity_actions"
    content = config.read_bytes()
    report["config_sha256"] = hashlib.sha256(content).hexdigest()
    started = time.monotonic()
    try:
        report["nginx_image"] = (
            docker("image", "inspect", nginx_image, "--format", "{{.Id}}")
            .decode()
            .strip()
        )
        report["tests_image"] = (
            docker("image", "inspect", "aqua-checks:p00", "--format", "{{.Id}}")
            .decode()
            .strip()
        )
        proxy = create(
            name + "-nginx",
            nginx_image,
            "--network=none",
            "--user=101:101",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
            "--tmpfs=/var/cache/nginx:rw,nosuid,nodev,size=33554432,uid=101,gid=101",
            "--entrypoint=/bin/sleep",
            command=("120",),
        )
        containers.append(proxy)
        docker("start", proxy)
        wrapped = (
            b"worker_processes 2; pid /tmp/nginx.pid; error_log /tmp/nginx-error.log warn; events { worker_connections 128; } http { access_log off; "
            + content
            + b"\n}"
        )
        docker("exec", "-i", proxy, "tee", "/tmp/nginx.conf", data=wrapped)
        docker("exec", proxy, "nginx", "-t", "-c", "/tmp/nginx.conf")
        docker(
            "exec", "-d", proxy, "nginx", "-c", "/tmp/nginx.conf", "-g", "daemon off;"
        )
        client = create(
            name + "-client",
            "aqua-checks:p00",
            "--network=container:" + proxy,
            "--user=1000:1000",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864,mode=1777",
            "--entrypoint=/bin/sleep",
            command=("120",),
        )
        containers.append(client)
        docker("start", client)
        docker(
            "exec",
            "-i",
            client,
            "tee",
            "/tmp/proxy_probe.py",
            data=(ROOT / "tools/checks" / probe_name).read_bytes(),
        )
        docker(
            "exec",
            "-i",
            client,
            "tee",
            "/tmp/p07_proxy_stream.py",
            data=(ROOT / "tools/checks/p07_proxy_stream.py").read_bytes(),
        )
        command = ["exec", client, "python", "-B", "/tmp/proxy_probe.py"]
        if baseline:
            command.append("--baseline")
        report["exercise"] = json.loads(docker(*command, timeout=60))
        report["resource_snapshots"] = [
            json.loads(line)
            for line in docker(
                "stats", "--no-stream", "--format", "{{json .}}", *containers
            )
            .decode()
            .splitlines()
        ]
        report["status"] = "red_finding_reproduced" if baseline else "passed"
    except (RuntimeError, subprocess.TimeoutExpired, ValueError) as error:
        report["error"] = str(error)
    finally:
        remaining = []
        for cid in reversed(containers):
            try:
                docker("rm", "--force", cid)
                check = subprocess.run(
                    ["docker", "container", "inspect", cid],
                    capture_output=True,
                    timeout=15,
                )
                if check.returncode != 1 or b"No such" not in check.stderr:
                    remaining.append(cid)
            except (RuntimeError, subprocess.TimeoutExpired):
                remaining.append(cid)
        report["cleanup"] = (
            "removed_and_absence_confirmed" if not remaining else "failed"
        )
        report["remaining_ids"] = remaining
        report["elapsed_seconds"] = round(time.monotonic() - started, 2)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))
    return int(
        report["status"] not in {"passed", "red_finding_reproduced"} or bool(remaining)
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "frontend/nginx.conf")
    parser.add_argument(
        "--output", type=Path, default=ROOT / ".check-results/proxy.json"
    )
    parser.add_argument("--baseline", action="store_true")
    parser.add_argument("--nginx-image", default=NGINX)
    parser.add_argument("--identity-actions", action="store_true")
    args = parser.parse_args()
    if args.baseline and args.identity_actions:
        parser.error("identity-actions cannot use an unsafe baseline")
    raise SystemExit(
        run(
            args.config,
            args.output,
            args.baseline,
            args.nginx_image,
            identity_actions=args.identity_actions,
        )
    )
