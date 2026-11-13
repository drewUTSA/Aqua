"""Run bounded P12 measurements using the existing isolated fixture contract."""

import argparse
import hashlib
import json
from pathlib import Path
import secrets
import subprocess

from run_backend import docker, provision_core, source_archive


def run(image: str, output: Path) -> int:
    """Keep every owned ID until removal and absence are confirmed."""
    owned = []
    report = {"status": "failed", "cleanup": "pending", "image": image}
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        archive = source_archive()
        report["source_archive_sha256"] = hashlib.sha256(archive).hexdigest()
        _, runner = provision_core(
            image=image,
            run_name="aqua-p12-capacity-" + secrets.token_hex(12),
            containers=owned,
            archive=archive,
        )
        raw = docker(
            "exec",
            "--workdir=/checks/backend",
            "-e",
            "PYTHONPATH=/checks/backend",
            runner,
            "python",
            "-B",
            "/checks/tools/checks/capacity_probe.py",
            timeout=120,
        )
        report["measurements"] = json.loads(raw)
        if report["measurements"]["status"] != "passed":
            raise RuntimeError("capacity_probe_incomplete")
        report["status"] = "passed"
    except (RuntimeError, subprocess.TimeoutExpired, OSError, ValueError) as error:
        report["error"] = str(error)
    finally:
        remaining = []
        for container in reversed(owned):
            try:
                docker("rm", "--force", container)
                check = subprocess.run(
                    ["docker", "container", "inspect", container],
                    capture_output=True,
                    timeout=15,
                )
                if check.returncode != 1 or b"No such" not in check.stderr:
                    remaining.append(container)
            except (RuntimeError, subprocess.TimeoutExpired):
                remaining.append(container)
        report["remaining_ids"] = remaining
        report["cleanup"] = "failed" if remaining else "removed_and_absence_confirmed"
        output.write_text(
            json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report, sort_keys=True))
    return int(report["status"] != "passed" or bool(remaining))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.image, args.output))
