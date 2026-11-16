"""Disposable nginx delivery checks: no ingress, host mounts or real upstream."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess

from run_backend import create, docker
from run_proxy import NGINX

ROOT = Path(__file__).resolve().parents[2]


def local_paths(source):
    """Extract the explicit literals from the three reviewed JS route sets."""
    result = set()
    for name in ("AUTH_PATHS", "ACCOUNT_ACTION_PATHS", "LOCAL_PATHS"):
        match = re.search(
            r"export const " + name + r" = new Set\(\[([^\]]*)\]\)", source
        )
        if match is None:
            raise ValueError("route_contract_changed")
        result.update(re.findall(r'"(/[^"\r\n]*)"', match.group(1)))
    if len(result) != 14:
        raise ValueError("route_contract_changed")
    return sorted(result)


def run(output, nginx_image=NGINX):
    if output.exists() or output.is_symlink():
        raise ValueError("output_already_exists")
    content = (ROOT / "frontend/nginx.conf").read_bytes()
    index = (ROOT / "frontend/index.html").read_bytes()
    paths = local_paths((ROOT / "frontend/src/services/routes.js").read_text())
    name = "aqua-public-delivery-test-" + secrets.token_hex(12)
    containers = []
    report = {
        "status": "failed",
        "network": "none",
        "cleanup": "pending",
        "config_sha256": hashlib.sha256(content).hexdigest(),
        "index_sha256": hashlib.sha256(index).hexdigest(),
    }
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
            "--memory=64m",
            "--memory-swap=64m",
            "--cpus=0.5",
            "--pids-limit=64",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=8388608,mode=1777",
            "--tmpfs=/var/cache/nginx:rw,nosuid,nodev,size=8388608,uid=101,gid=101",
            "--tmpfs=/usr/share/nginx/html:rw,nosuid,nodev,size=1048576,uid=101,gid=101",
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
        docker(
            "exec", "-i", proxy, "tee", "/usr/share/nginx/html/index.html", data=index
        )
        docker("exec", proxy, "mkdir", "/usr/share/nginx/html/assets")
        docker(
            "exec",
            "-i",
            proxy,
            "tee",
            "/usr/share/nginx/html/assets/synthetic.js",
            data=b"/* synthetic asset */",
        )
        docker(
            "exec",
            "-i",
            proxy,
            "tee",
            "/usr/share/nginx/html/fixture-icon.svg",
            data=b"<svg/>",
        )
        docker("exec", proxy, "nginx", "-t", "-c", "/tmp/nginx.conf")
        docker(
            "exec", "-d", proxy, "nginx", "-c", "/tmp/nginx.conf", "-g", "daemon off;"
        )
        client = create(
            name + "-client",
            "aqua-checks:p00",
            "--network=container:" + proxy,
            "--user=1000:1000",
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=0.5",
            "--pids-limit=64",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=8388608,mode=1777",
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
            "/tmp/delivery_probe.py",
            data=(ROOT / "tools/checks/public_delivery_proxy_probe.py").read_bytes(),
        )
        report["exercise"] = json.loads(
            docker(
                "exec",
                client,
                "python",
                "-B",
                "/tmp/delivery_probe.py",
                json.dumps(paths),
                timeout=30,
            )
        )
        report["status"] = "passed"
    except (RuntimeError, subprocess.TimeoutExpired, ValueError):
        report["error"] = "isolated_delivery_fixture_failed"
    finally:
        remaining = []
        for container in reversed(containers):
            try:
                docker("rm", "--force", container)
                absence = subprocess.run(
                    ["docker", "container", "inspect", container],
                    capture_output=True,
                    timeout=15,
                )
                if absence.returncode != 1 or b"No such" not in absence.stderr:
                    remaining.append(container)
            except (RuntimeError, subprocess.TimeoutExpired):
                remaining.append(container)
        report["cleanup"] = (
            "removed_and_absence_confirmed" if not remaining else "failed"
        )
        report["remaining_ids"] = remaining
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as destination:
            destination.write(json.dumps(report, indent=2) + "\n")
        print(json.dumps(report))
    return int(report["status"] != "passed" or bool(remaining))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nginx-image", default=NGINX)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.output, args.nginx_image))
