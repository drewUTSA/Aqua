"""Fixed-socket Docker commands and allowlisted source packaging."""

import io
import json
import re
import subprocess
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PURPOSE = "p05-browser-fixture"
DOCKER_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/proc/self/fd",
    "DOCKER_CONFIG": "/proc/self/fd",
}


def docker(*args: str, data: bytes | None = None, timeout: int = 60) -> bytes:
    """Fixed Docker socket and discarded command diagnostics; no env/config read."""
    result = subprocess.run(
        ["/usr/bin/docker", "--host=unix:///var/run/docker.sock", *args],
        input=data,
        check=False,
        capture_output=True,
        timeout=timeout,
        env=DOCKER_ENV,
    )
    if result.returncode:
        raise RuntimeError("fixture_docker_operation_failed")
    return result.stdout


def owned_resource(kind: str, name: str, run: str) -> str | None:
    """Read only name/ID/labels; an uncertain inspect is never proof of absence."""
    if not re.fullmatch(r"aqua-p05-browser-[a-f0-9]{24}", run) or (kind, name) not in {
        ("container", run + "-pg"),
        ("container", run + "-api"),
        ("volume", run + "-socket"),
    }:
        raise ValueError("fixture_resource_scope_invalid")
    template = (
        "{{json .Id}}\n{{json .Name}}\n{{json .Config.Labels}}"
        if kind == "container"
        else "{{json .Name}}\n{{json .Name}}\n{{json .Labels}}"
    )
    result = subprocess.run(
        [
            "/usr/bin/docker",
            "--host=unix:///var/run/docker.sock",
            kind,
            "inspect",
            name,
            "--format",
            template,
        ],
        capture_output=True,
        check=False,
        timeout=10,
        env=DOCKER_ENV,
    )
    absent = (
        rb"no such (?:container|object|volume):\s*"
        + re.escape(name.encode())
        + rb"\s*$"
    )
    # Docker 29 volume inspect reverses the older missing-volume diagnostic.
    # Both recognized forms must include this exact run-owned resource name.
    absent_volume = rb"get " + re.escape(name.encode()) + rb": no such volume\s*$"
    if result.returncode == 1 and (
        re.search(absent, result.stderr.lower())
        or (kind == "volume" and re.search(absent_volume, result.stderr.lower()))
    ):
        return None
    if result.returncode or len(result.stdout) > 4096:
        raise RuntimeError("fixture_resource_inspect_failed")
    fields = result.stdout.splitlines()
    if len(fields) != 3:
        raise RuntimeError("fixture_resource_metadata_invalid")
    identifier, observed_name, labels = (json.loads(field) for field in fields)
    if (
        observed_name != ("/" + name if kind == "container" else name)
        or not isinstance(labels, dict)
        or labels.get("io.aqua.purpose") != PURPOSE
        or labels.get("io.aqua.run") != run
        or not isinstance(identifier, str)
        or (kind == "container" and not re.fullmatch(r"[a-f0-9]{64}", identifier))
        or (kind == "volume" and identifier != name)
    ):
        raise RuntimeError("fixture_resource_ownership_mismatch")
    return identifier


def source_archive() -> bytes:
    """Allowlisted source and corpus only; no dotenv, Git data or symlinks."""
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode="w") as archive:
        for folder in ("backend", "tools/checks", "ops"):
            for path in sorted((ROOT / folder).rglob("*")):
                if path.is_symlink():
                    raise RuntimeError("fixture_source_symlink")
                if not path.is_file() or any(
                    part.startswith(".") or part in {"__pycache__", "results"}
                    for part in path.relative_to(ROOT).parts
                ):
                    continue
                asset = path.parent == ROOT / "backend/auth" and path.name in {
                    "password_blocklist_sha256.txt",
                    "password_blocklist_LICENSE.txt",
                    "password_blocklist_provenance.json",
                }
                if not asset and path.suffix not in {".py", ".sql", ".psql", ".ini"}:
                    continue
                content = path.read_bytes()
                item = tarfile.TarInfo(path.relative_to(ROOT).as_posix())
                item.size, item.mode, item.uid, item.gid = (
                    len(content),
                    0o644,
                    1000,
                    1000,
                )
                archive.addfile(item, io.BytesIO(content))
    if stream.tell() > 16 * 1024 * 1024:
        raise RuntimeError("fixture_source_limit")
    return stream.getvalue()


def create(name: str, image: str, *args: str, command: tuple[str, ...] = ()) -> str:
    match = re.fullmatch(r"(aqua-p05-browser-[a-f0-9]{24})-(?:pg|api)", name)
    if match is None:
        raise ValueError("fixture_container_scope_invalid")
    result = (
        docker(
            "create",
            "--name",
            name,
            "--label",
            "io.aqua.purpose=p05-browser-fixture",
            "--label",
            "io.aqua.run=" + match[1],
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--memory=1g",
            "--memory-swap=1g",
            "--cpus=2",
            "--pids-limit=128",
            "--log-driver=none",
            *args,
            image,
            *command,
        )
        .decode()
        .strip()
    )
    if not re.fullmatch(r"[a-f0-9]{64}", result):
        raise RuntimeError("fixture_container_id_invalid")
    return result
