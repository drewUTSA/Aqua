"""Run frozen replay in the existing networkless, disposable PG fixture pair.

No live DSNs, provider keys or environment files are accepted or packaged.
The output must be a new file outside the application source checkout.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import secrets
import subprocess
import tarfile

from run_backend import ROOT, docker, provision_core, source_archive

FIXTURE = ROOT / "tools/checks/fixtures/ai_replay_dataset.jsonl"


def replay_archive() -> tuple[bytes, str]:
    """Extend the closed source archive by exactly one bounded synthetic asset."""
    if FIXTURE.is_symlink() or not FIXTURE.is_file():
        raise ValueError("replay_fixture_not_regular")
    raw = FIXTURE.read_bytes()
    if not 0 < len(raw) <= 262144:
        raise ValueError("replay_fixture_byte_budget")
    stream = io.BytesIO(source_archive())
    with tarfile.open(fileobj=stream, mode="a") as archive:
        name = FIXTURE.relative_to(ROOT).as_posix()
        if name in archive.getnames():
            raise ValueError("replay_fixture_duplicate_archive_member")
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.uid, info.gid = len(raw), 0o644, 1000, 1000
        archive.addfile(info, io.BytesIO(raw))
    return stream.getvalue(), hashlib.sha256(raw).hexdigest()


def run(image: str, output: Path) -> int:
    """Retain all owned IDs until deletion and absence are both confirmed."""
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise ValueError("replay_requires_exact_image_id")
    output = output.resolve()
    if output.is_relative_to(ROOT.resolve()):
        raise ValueError("replay_output_must_be_outside_source")
    output.parent.mkdir(parents=True, exist_ok=True)
    # Claim create-only output before creating any Docker resource.
    with output.open("x", encoding="utf-8") as handle:
        owned, results = [], []
        report = {
            "status": "failed",
            "cleanup": "pending",
            "image": image,
            "kind": "networkless_frozen_replay",
            "real_model_quality_measured": False,
        }
        try:
            if (
                docker("image", "inspect", image, "--format", "{{.Id}}")
                .decode()
                .strip()
                != image
            ):
                raise ValueError("replay_image_identity_mismatch")
            archive, digest = replay_archive()
            report.update(
                source_archive_sha256=hashlib.sha256(archive).hexdigest(),
                dataset_sha256=digest,
            )
            _, runner = provision_core(
                image=image,
                run_name="aqua-ai-replay-" + secrets.token_hex(12),
                containers=owned,
                archive=archive,
            )
            for dataset in ("bank", "pagila"):
                raw = docker(
                    "exec",
                    "--workdir=/checks",
                    runner,
                    "python",
                    "-B",
                    "/checks/eval/replay.py",
                    dataset,
                    timeout=120,
                )
                if len(raw) > 262144:
                    raise ValueError("replay_report_byte_budget")
                result = json.loads(raw)
                results.append(result)
                if (
                    result["status"] != "passed"
                    or result["dataset_sha256"] != digest
                    or result["dataset"] != dataset
                    or result["real_model_quality_measured"] is not False
                ):
                    raise ValueError("replay_dataset_failed")
            report["status"] = "passed"
        except (
            RuntimeError,
            subprocess.TimeoutExpired,
            OSError,
            ValueError,
            KeyError,
        ) as error:
            report["error_type"] = type(error).__name__
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
                except (RuntimeError, subprocess.TimeoutExpired, OSError):
                    remaining.append(container)
            report.update(
                results=results,
                remaining_ids=remaining,
                cleanup="failed" if remaining else "removed_and_absence_confirmed",
            )
            if remaining:
                report["status"] = "failed"
            handle.write(json.dumps(report, sort_keys=True, indent=2) + "\n")
            handle.flush()
            print(
                json.dumps(
                    {key: value for key, value in report.items() if key != "results"},
                    sort_keys=True,
                )
            )
    return int(report["status"] != "passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(run(args.image, args.output))
