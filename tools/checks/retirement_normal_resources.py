"""Five closed QA roles; ordinary web probes use compiled /app without overlay."""

import json
import re
import subprocess

import p05_browser_docker as commands
from retirement_host_resources import Resources, PURPOSE

ROLES = {"seed", "normal-purge", "normal-closed", "normal-recover", "normal-ready"}


class NormalResources(Resources):
    def inspect(self, role):
        if role not in ROLES:
            return super().inspect(role)
        name = self.run + "-" + role
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
            raise RuntimeError("normal_fixture_inspect_unconfirmed")
        values = result.stdout.splitlines()
        if len(values) != 4:
            raise RuntimeError("normal_fixture_metadata_invalid")
        identifier, observed, labels, image = map(json.loads, values)
        if (
            type(identifier) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or observed != "/" + name
            or labels.get("io.aqua.run") != self.run
            or labels.get("io.aqua.purpose") != PURPOSE
            or image != self.image
            or role in self.created
            and identifier != self.created[role]
        ):
            raise RuntimeError("normal_fixture_wrong_owner")
        self.created[role] = identifier
        self.uncertain.discard(role)
        return identifier

    def create(self, role):
        if role not in ROLES:
            return super().create(role)
        if role in self.attempted or not self.append_ready:
            raise RuntimeError("normal_fixture_not_admitted")
        self.verify_layout()
        self.attempted.append(role)
        self.uncertain.add(role)
        args = [
            "create",
            "--name=" + self.run + "-" + role,
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
            "--interactive",
            "--workdir=/app",
            "--tmpfs=/tmp:rw,nosuid,nodev,size=134217728,mode=1777",
            "--mount=type=bind,src="
            + str(self.root / "source")
            + ",dst=/checks,readonly",
            "--mount=type=bind,src="
            + str(self.root / "backend")
            + ",dst=/run/aqua-retirement,readonly",
            "--mount=type=bind,src="
            + str(self.root / "authority/checkpoints.bin")
            + ",dst=/run/aqua-retirement/checkpoints.bin,readonly",
            "--mount=type=bind,src="
            + str(self.root / "mail/physical.lock")
            + ",dst=/run/aqua-retirement/mail-worker.lock,readonly",
            "--mount=type=volume,src=" + self.volume + ",dst=/run/aqua-app-db,readonly",
            "--env=PYTHONPATH=/app:/checks:/checks/tools/checks/retirement_fixture"
            + (":/checks/backend/tests" if role == "seed" else ""),
            "--env=PYTHON_DOTENV_DISABLED=1",
            "--env=PYTHONDONTWRITEBYTECODE=1",
            "--env=AQUA_RETIREMENT_NATIVE_FIXTURE=true",
        ]
        if role == "seed":
            args += ["--env=AQUA_RETIREMENT_NORMAL_SEED=true"]
            program = [
                "-u",
                "/checks/tools/checks/retirement_fixture/integration_cases.py",
            ]
        elif role == "normal-recover":
            program = [
                "-u",
                "/checks/tools/checks/retirement_fixture/normal_recover.py",
                "--execute",
            ]
        else:
            program = [
                "-u",
                "/checks/tools/checks/retirement_fixture/normal_runtime_probe.py",
                "--execute",
            ]
        identifier = (
            commands.docker(
                *args,
                "--entrypoint=python",
                self.image,
                *program,
                timeout=self.timeout(15),
            )
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise RuntimeError("normal_fixture_create_unconfirmed")
        self.created[role] = identifier
        if self.inspect(role) != identifier:
            raise RuntimeError("normal_fixture_create_changed")
        return identifier

    def remove(self, role):
        if role not in ROLES:
            return super().remove(role)
        identifier = self.inspect(role)
        if identifier is not None:
            commands.docker("rm", "--force", identifier, timeout=self.timeout(15))
        if role not in self.created or self.inspect(role) is not None:
            return False
        if commands.docker(
            "ps",
            "--all",
            "--no-trunc",
            "--filter=id=" + self.created[role],
            "--format={{.ID}}",
            timeout=self.timeout(10),
        ).strip():
            return False
        self.uncertain.discard(role)
        return True
