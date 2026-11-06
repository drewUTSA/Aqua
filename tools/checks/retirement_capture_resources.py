"""One additional cap-zero capture role in the existing exact-owned native fixture."""

import json
import re
import subprocess

import p05_browser_docker as commands
from retirement_host_resources import Resources, PURPOSE


class CaptureResources(Resources):
    def __init__(self, run, image, setter, source):
        super().__init__(run, image, setter)
        self.source_sha256 = source
        self.capture_id = None

    def inspect(self, role):
        if role != "capture":
            return super().inspect(role)
        name = self.run + "-capture"
        result = subprocess.run(
            [
                "/usr/bin/docker",
                "--host=unix:///var/run/docker.sock",
                "container",
                "inspect",
                name,
                "--format={{json .Id}}\n{{json .Name}}\n{{json .Config.Labels}}\n{{json .Image}}",
            ],
            capture_output=True,
            timeout=self.timeout(10),
            env=commands.DOCKER_ENV,
            close_fds=True,
        )
        if (
            result.returncode == 1
            and result.stdout in {b"", b"\n", b"[]\n"}
            and re.search(
                rb"no such (?:object|container):\s*"
                + re.escape(name.encode())
                + rb"\s*$",
                result.stderr.lower(),
            )
        ):
            return None
        if result.returncode or len(result.stdout) > 4096:
            raise RuntimeError("capture_inspect_unconfirmed")
        values = result.stdout.splitlines()
        if len(values) != 4:
            raise RuntimeError("capture_metadata_invalid")
        identifier, observed, labels, image = map(json.loads, values)
        if (
            type(identifier) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or observed != "/" + name
            or labels.get("io.aqua.run") != self.run
            or labels.get("io.aqua.purpose") != PURPOSE
            or image != self.image
            or self.capture_id is not None
            and self.capture_id != identifier
        ):
            raise RuntimeError("capture_wrong_identity")
        self.capture_id = identifier
        self.uncertain.discard(role)
        return identifier

    def create(self, role):
        if role != "capture":
            return super().create(role)
        if role in self.attempted or not self.append_ready:
            raise RuntimeError("capture_not_admitted")
        self.verify_layout()
        self.attempted.append(role)
        self.uncertain.add(role)
        identifier = (
            commands.docker(
                "create",
                "--name=" + self.run + "-capture",
                "--label=io.aqua.run=" + self.run,
                "--label=io.aqua.purpose=" + PURPOSE,
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--user=1000:1000",
                "--memory=1g",
                "--memory-swap=1g",
                "--cpus=1",
                "--pids-limit=128",
                "--restart=no",
                "--log-driver=none",
                "--no-healthcheck",
                "--stop-timeout=1",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=8388608,mode=1777",
                "--mount=type=bind,src="
                + str(self.root / "source")
                + ",dst=/checks,readonly",
                "--mount=type=bind,src="
                + str(self.root / "backend")
                + ",dst=/run/aqua-retirement,readonly",
                "--mount=type=bind,src="
                + str(self.root / "authority/checkpoints.bin")
                + ",dst=/run/aqua-retirement/checkpoints.bin,readonly",
                "--mount=type=volume,src="
                + self.volume
                + ",dst=/run/aqua-app-db,readonly",
                "--env=PYTHONPATH=/app:/checks:/checks/tools/checks/retirement_fixture",
                "--env=PYTHONDONTWRITEBYTECODE=1",
                "--env=PYTHON_DOTENV_DISABLED=1",
                "--env=AQUA_RETIREMENT_NATIVE_FIXTURE=true",
                "--workdir=/app",
                "--interactive",
                "--entrypoint=python",
                self.image,
                "-u",
                "/checks/tools/checks/retirement_fixture/capture129.py",
                "--execute",
                "--run",
                self.run,
                "--image",
                self.image,
                "--source-sha256",
                self.source_sha256,
                timeout=self.timeout(15),
            )
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise RuntimeError("capture_create_unconfirmed")
        self.capture_id = identifier
        if self.inspect(role) != identifier:
            raise RuntimeError("capture_create_identity_changed")
        return identifier

    def remove(self, role):
        if role != "capture":
            return super().remove(role)
        identifier = self.inspect(role)
        if identifier is not None:
            commands.docker("rm", "--force", identifier, timeout=self.timeout(10))
        if self.capture_id is None or self.inspect(role) is not None:
            return False
        original = commands.docker(
            "ps",
            "--all",
            "--no-trunc",
            "--filter=id=" + self.capture_id,
            "--format={{.ID}}",
            timeout=self.timeout(10),
        ).strip()
        if original:
            return False
        self.uncertain.discard(role)
        return True
