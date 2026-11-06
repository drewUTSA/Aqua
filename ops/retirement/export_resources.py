"""Two exact-owned cap-zero containers for operator observation and archival."""

import json
import re
import secrets
import subprocess
import time

if __package__:
    from .operator_files import PRIVATE
    from .operator_scope import PRODUCTION
    from .export_code import BOOTSTRAP
else:
    from operator_files import PRIVATE
    from operator_scope import PRODUCTION
    from export_code import BOOTSTRAP

POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)
PURPOSE = "retirement-archive-operator"
SOCKET = "aqua_app_sockets"
DOCKER = [
    "/usr/bin/docker",
    "--host=unix:///var/run/docker.sock",
    "--config=/proc/self/fd",
]
ENV = {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": "/proc/self/fd"}
DUMP = "IFS= read -r PGPASSWORD || exit 1; export PGPASSWORD; exec pg_dump -h /run/aqua-app-db -p 5432 -U aqua_retirement_backup -d aqua_retirement -Fc --no-owner --no-privileges --schema=retirement"


class Owned:
    roles = frozenset({"peer", "dump"})
    purpose = PURPOSE

    def __init__(self, profile: dict, scope=PRODUCTION):
        self.profile, self.scope = profile, scope
        self.name = "aqua-retirement-archive-" + secrets.token_hex(16)
        self.attempted = []
        self.created = {}
        self.uncertain = set()
        self.processes = []
        self.until = time.monotonic() + 120

    @property
    def private(self):
        return PRIVATE if self.scope is PRODUCTION else self.scope.private

    @property
    def socket(self):
        return SOCKET if self.scope is PRODUCTION else self.scope.socket

    def seconds(self, maximum: float = 15) -> float:
        value = min(maximum, self.until - time.monotonic())
        if value <= 0:
            raise RuntimeError("retirement_export_deadline")
        return value

    def command(self, *arguments: str, maximum_seconds: float = 15) -> bytes:
        result = subprocess.run(
            [*DOCKER, *arguments],
            capture_output=True,
            timeout=self.seconds(maximum_seconds),
            env=ENV,
            stdin=subprocess.DEVNULL,
            close_fds=True,
        )
        if result.returncode or len(result.stdout) > 65536:
            raise RuntimeError("retirement_export_container_operation_failed")
        return result.stdout

    def inspect(self, role: str) -> str | None:
        if role not in self.roles:
            raise ValueError("retirement_export_role_invalid")
        name = self.name + "-" + role
        result = subprocess.run(
            [
                *DOCKER,
                "container",
                "inspect",
                name,
                "--format={{json .Id}}\n{{json .Name}}\n{{json .Config.Labels}}\n{{json .Config.Image}}",
            ],
            capture_output=True,
            timeout=self.seconds(10),
            env=ENV,
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
            raise RuntimeError("retirement_export_absence_unconfirmed")
        fields = result.stdout.splitlines()
        if len(fields) != 4:
            raise RuntimeError("retirement_export_identity_invalid")
        identifier, observed, labels, image = map(json.loads, fields)
        if (
            not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or observed != "/" + name
            or labels.get("io.aqua.run") != self.name
            or labels.get("io.aqua.purpose") != self.purpose
            or labels.get("io.aqua.qa-run") != self.scope.qa_run
            or image != (POSTGRES if role == "dump" else self.profile["runtime_image"])
            or role in self.created
            and identifier != self.created[role]
        ):
            raise RuntimeError("retirement_export_wrong_resource_owner")
        if role in self.uncertain:
            self.created[role] = identifier
            self.uncertain.discard(role)
        return identifier

    def remember(self, role: str, identifier: str) -> str:
        """Retain a valid daemon-returned ID before the first name inspection."""
        if (
            role not in self.roles
            or role not in self.attempted
            or not re.fullmatch(r"[a-f0-9]{64}", identifier)
        ):
            raise RuntimeError("retirement_export_create_unconfirmed")
        self.created[role] = identifier
        return identifier

    def create(self, role: str, action: str = "export") -> str:
        if (
            role not in {"peer", "dump"}
            or role in self.attempted
            or action not in {"head", "export"}
        ):
            raise ValueError("retirement_export_role_reused_or_invalid")
        self.attempted.append(role)
        self.uncertain.add(role)
        args = [
            "container",
            "create",
            "--pull=never",
            "--name=" + self.name + "-" + role,
            "--label=io.aqua.run=" + self.name,
            "--label=io.aqua.purpose=" + self.purpose,
            *(
                ["--label=io.aqua.qa-run=" + self.scope.qa_run]
                if self.scope.qa_run is not None
                else []
            ),
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--pids-limit=64",
            "--cpus=1",
            "--restart=no",
            "--log-driver=none",
            "--no-healthcheck",
            "--stop-timeout=1",
            "--interactive",
        ]
        if role == "dump":
            args += [
                "--user=999:1000",
                "--memory=256m",
                "--memory-swap=256m",
                "--mount=type=volume,src="
                + self.socket
                + ",dst=/run/aqua-app-db,readonly",
                "--entrypoint=/bin/sh",
                POSTGRES,
                "-c",
                DUMP,
            ]
        else:
            source = (
                self.private / "operator" / ("public" if action == "head" else "export")
            )
            args += [
                "--user=1000:1000",
                "--memory=1g",
                "--memory-swap=1g",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=8388608,mode=1777",
                "--mount=type=bind,src="
                + str(source)
                + ",dst=/run/aqua-retirement-backup,readonly",
                "--mount=type=bind,src="
                + str(self.private / "authority/checkpoints.bin")
                + ",dst=/run/aqua-retirement-backup/checkpoints.bin,readonly",
                "--mount=type=bind,src="
                + str(self.private / "operator/code")
                + ",dst=/operator,readonly",
            ]
            if action == "export":
                args += [
                    "--mount=type=volume,src="
                    + self.socket
                    + ",dst=/run/aqua-app-db,readonly",
                    "--mount=type=bind,src="
                    + str(self.private / "backend/identity.key")
                    + ",dst=/run/aqua-retirement-backup/identity.key,readonly",
                    "--mount=type=bind,src="
                    + str(self.private / "host/signing.key")
                    + ",dst=/run/aqua-retirement-backup/signing.key,readonly",
                ]
            args += [
                "--workdir=/app",
                "--entrypoint=python",
                self.profile["runtime_image"],
                "-E",
                "-s",
                "-B",
                "-c",
                BOOTSTRAP,
                self.profile["code_manifest_sha256"],
                action,
            ]
        identifier = self.remember(role, self.command(*args).decode().strip())
        if identifier != self.inspect(role):
            raise RuntimeError("retirement_export_create_identity_mismatch")
        self.uncertain.discard(role)
        return identifier

    def start(self, role: str, action: str = "export"):
        identifier = self.create(role, action)
        process = subprocess.Popen(
            [*DOCKER, "container", "start", "--attach", "--interactive", identifier],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=ENV,
            bufsize=0,
            close_fds=True,
            start_new_session=True,
        )
        self.processes.append(process)
        return process

    def remove(self, role: str) -> bool:
        identifier = self.inspect(role)
        if identifier is not None:
            self.command("container", "rm", "--force", identifier)
        if role not in self.created or self.inspect(role) is not None:
            return False
        # Renaming a known container never makes its original ID disappear.
        # Do not remove an unvalidated renamed/foreign object: remain red.
        if self.command(
            "ps",
            "--all",
            "--no-trunc",
            "--filter=id=" + self.created[role],
            "--format={{.ID}}",
        ).strip():
            return False
        self.uncertain.discard(role)
        return True

    def close(self) -> None:
        self.until = time.monotonic() + 45
        remaining = []
        for role in reversed(self.attempted):
            try:
                if not self.remove(role):
                    remaining.append(role)
            except Exception:
                remaining.append(role)
        # A dead client does not prove pg_dump or the key custodian has exited.
        for process in self.processes:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=3)
        if remaining:
            raise RuntimeError("retirement_export_owned_cleanup_unconfirmed")
