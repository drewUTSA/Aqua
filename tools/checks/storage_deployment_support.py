"""Private synthetic deployment helpers; ownership-checked cleanup only."""

import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
from types import ModuleType
from contextlib import redirect_stdout


def load(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def cleanup(
    root: Path, run_id: str, container: str, volume: str, sockets: str, report: dict
) -> None:
    errors = []
    for kind, name in [
        ("container", container),
        ("volume", sockets),
        ("volume", volume),
    ]:
        inspected = subprocess.run(
            ["/usr/bin/docker", kind, "inspect", name],
            capture_output=True,
            timeout=15,
        )
        if inspected.returncode == 0:
            item = json.loads(inspected.stdout)[0]
            labels = (
                item.get("Labels", {})
                if kind != "container"
                else item["Config"].get("Labels", {})
            )
            owned = labels.get("com.docker.compose.project") == run_id
            if kind == "volume":
                owned = name in {volume, sockets} and bool(
                    labels.get("io.aqua.install")
                )
            if not owned:
                errors.append(kind + "_ownership_mismatch")
                continue
            args = ["/usr/bin/docker", kind, "rm"]
            if kind == "container":
                args.append("--force")
            result = subprocess.run(
                args + [item["Id"] if kind == "container" else name],
                capture_output=True,
                timeout=25,
            )
            absent = subprocess.run(
                ["/usr/bin/docker", kind, "inspect", name],
                capture_output=True,
                timeout=15,
            )
            if result.returncode or absent.returncode != 1:
                errors.append(kind + "_cleanup_failed")
    if errors:
        report["cleanup_errors"] = errors
        report["status"] = "failed"
    else:
        shutil.rmtree(root)
        report["cleanup"] = "removed_and_absence_confirmed"


def verify_export(root: Path, container: str) -> dict:
    exporter = load("aqua_fixture_export", root / "ops/appdb/export.py")
    exporter.CONTAINER = container
    stream = io.BytesIO()

    class Sink:
        buffer = stream

        def isatty(self) -> bool:
            return False

    with redirect_stdout(Sink()):
        exporter.main()
    data = stream.getvalue()
    assert data.startswith(b"PGDMP")
    return {
        "status": "passed",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "storage": "memory_only",
    }
