"""Explicitly owned Linux-only mounts and capability boundary for inode proof."""

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time

import p05_browser_docker as commands

ROOT = Path(__file__).resolve().parents[2]
BASE = Path("/srv/bank-ai/.check-results")
PURPOSE = "p11bc-disposable-inode-proof"
RUN = re.compile(r"p11bc-durability-[a-f0-9]{24}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")


def source() -> tuple[dict[str, bytes], str]:
    """Bind every current retirement module and both probe programs."""
    names = (
        sorted((ROOT / "backend/retirement").glob("*.py"))
        + [
            ROOT / "tools/checks/retirement_fixture" / name
            for name in ("kernel_probe.py", "append_flags.py")
        ]
        + [ROOT / "ops/retirement/initialize.py"]
        + [
            ROOT / "tools/checks" / name
            for name in (
                "run_retirement_durability.py",
                "retirement_durability_resources.py",
                "p05_browser_docker.py",
            )
        ]
    )
    contents = {}
    for path in names:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("durability_source_invalid")
        contents[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    hashes = {name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()}
    digest = hashlib.sha256(
        json.dumps(hashes, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return contents, digest


def validate_base(base: Path) -> None:
    """The executor cannot be pointed at a private runtime or existing ledger."""
    if (
        base != BASE
        or base.resolve(strict=True) != base
        or os.geteuid() != 1000
        or os.name != "posix"
        or not Path("/proc/sys/kernel/ostype").read_text().strip() == "Linux"
    ):
        raise RuntimeError("durability_host_scope_invalid")
    metadata = base.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != 1000:
        raise RuntimeError("durability_host_owner_invalid")


class Resources:
    """Never inspect, start or remove a container outside this exact new run."""

    def __init__(self, run: str, image: str, directory: Path, setter: bytes) -> None:
        if not RUN.fullmatch(run) or not IMAGE.fullmatch(image):
            raise ValueError("durability_resource_pin_invalid")
        if directory != BASE / run or directory.resolve(strict=True) != directory:
            raise ValueError("durability_mount_scope_invalid")
        self.run, self.image, self.directory = run, image, directory
        self.setter = setter.decode("utf-8")
        info = (directory / "authority").lstat()
        self.authority_identity = info.st_dev, info.st_ino
        self.deadline = time.monotonic() + 50
        self.attempted: list[str] = []

    def remaining(self) -> float:
        """Every work command shares the same finite50-second work window."""
        value = min(15, self.deadline - time.monotonic())
        if value <= 0:
            raise RuntimeError("durability_work_deadline")
        return value

    def identifier(self, role: str) -> str | None:
        """Accept only exact named absence or matching run/purpose labels."""
        if role not in {"initialize", "probe", "set", "clear"}:
            raise ValueError("durability_role_invalid")
        name = self.run + "-" + role
        result = subprocess.run(
            [
                "/usr/bin/docker",
                "--host=unix:///var/run/docker.sock",
                "container",
                "inspect",
                name,
                "--format={{json .Id}}\n{{json .Name}}\n{{json .Config.Labels}}",
            ],
            env=commands.DOCKER_ENV,
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 1 and re.search(
            rb"no such (?:container|object):\s*" + re.escape(name.encode()) + rb"\s*$",
            result.stderr.lower(),
        ):
            return None
        if result.returncode or len(result.stdout) > 4096:
            raise RuntimeError("durability_absence_unconfirmed")
        fields = result.stdout.splitlines()
        if len(fields) != 3:
            raise RuntimeError("durability_metadata_invalid")
        identifier, observed, labels = map(json.loads, fields)
        if (
            not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or observed != "/" + name
            or labels.get("io.aqua.run") != self.run
            or labels.get("io.aqua.purpose") != PURPOSE
        ):
            raise RuntimeError("durability_cleanup_owner_mismatch")
        return identifier

    def create(self, role: str) -> str:
        """Only the setter receives three capabilities and only fixture mounts."""
        if (
            role not in {"initialize", "probe", "set", "clear"}
            or role in self.attempted
        ):
            raise ValueError("durability_role_reused")
        self.attempted.append(role)
        arguments = [
            "create",
            "--name=" + self.run + "-" + role,
            "--label=io.aqua.run=" + self.run,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--memory=128m",
            "--memory-swap=128m",
            "--cpus=1",
            "--pids-limit=32",
            "--log-driver=none",
            "--mount=type=bind,src="
            + str(self.directory / "authority")
            + ",dst=/fixture/authority",
            "--env=PYTHONPATH=/checks/backend",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--entrypoint=python",
        ]
        if role in {"initialize", "probe"}:
            arguments += [
                "--user=1000:1000",
                "--interactive",
                "--mount=type=bind,src="
                + str(self.directory / "source")
                + ",dst=/checks,readonly",
            ]
            program = ["-u", "/checks/tools/checks/retirement_fixture/kernel_probe.py"]
            if role == "initialize":
                program.append("--initialize")
        else:
            arguments += ["--user=0:0"] + [
                "--cap-add=" + cap
                for cap in ("LINUX_IMMUTABLE", "FOWNER", "DAC_OVERRIDE")
            ]
            arguments += [
                "--env=AQUA_FIXTURE_DEVICE=" + str(self.authority_identity[0]),
                "--env=AQUA_FIXTURE_INODE=" + str(self.authority_identity[1]),
            ]
            # Run exact previously fingerprinted bytes, never a mutable
            # bind-mounted privileged program. The only mount is the fixture.
            program = ["-c", self.setter, role]
        raw = (
            commands.docker(*arguments, self.image, *program, timeout=self.remaining())
            .decode()
            .strip()
        )
        if raw != self.identifier(role):
            raise RuntimeError("durability_create_identity_mismatch")
        return raw

    def flag(self, operation: str) -> None:
        """A failure stays red; unsupported filesystems never receive a seam."""
        if operation == "clear":
            self.deadline = time.monotonic() + 30
        identifier = self.create(operation)
        commands.docker("start", "--attach", identifier, timeout=self.remaining())
        exit_code = commands.docker(
            "inspect",
            identifier,
            "--format={{.State.Running}} {{.State.ExitCode}}",
            timeout=self.remaining(),
        )
        if exit_code.strip() != b"false 0":
            raise RuntimeError("durability_real_inode_flag_failed")

    def remove(self, role: str) -> bool:
        """Stop the probe before allowing privileged fixture-flag cleanup."""
        identifier = self.identifier(role)
        if identifier is not None:
            commands.docker("rm", "--force", identifier, timeout=15)
        return self.identifier(role) is None
