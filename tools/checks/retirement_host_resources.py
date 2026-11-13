"""Own only a new synthetic native host fixture and explicit private mounts."""

import json
from pathlib import Path
import re
import subprocess
import time

import p05_browser_docker as commands
from p05_browser_protocol import POSTGRES

BASE = Path("/srv/bank-ai/.check-results")
RUN = re.compile(r"aqua-retirement-host-[a-f0-9]{24}\Z")
IMAGE = re.compile(r"sha256:[a-f0-9]{64}\Z")
ROLE = re.compile(
    r"(?:pg|initialize|set|clear|api|crash|poison|mail|publish[0-9]{1,2}|web[0-9]{1,2})\Z"
)
PURPOSE = "p11bc-native-composition"


def private_directory(path: Path) -> None:
    path.mkdir(mode=0o700)
    import os

    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        if os.fstat(fd).st_uid != 1000:
            raise RuntimeError("native_fixture_directory_owner_invalid")
        os.fchmod(fd, 0o700)
    finally:
        os.close(fd)


class Resources:
    def __init__(self, run: str, image: str, setter: bytes):
        if not RUN.fullmatch(run) or not IMAGE.fullmatch(image):
            raise ValueError("native_fixture_exact_scope_required")
        self.run, self.image, self.setter = run, image, setter.decode()
        self.root, self.volume = BASE / run, run + "-socket"
        self.attempted, self.uncertain = [], set()
        self.created = {}
        self.volume_attempted = False
        self.volume_uncertain = False
        self.layout = {}
        self.initializer_finished = False
        self.append_ready = False
        self.cleanup_until = None

    def timeout(self, maximum: float) -> float:
        if self.cleanup_until is None:
            return maximum
        remaining = min(maximum, self.cleanup_until - time.monotonic())
        if remaining <= 0:
            raise RuntimeError("native_fixture_cleanup_deadline")
        return remaining

    def admit(self, role: str) -> None:
        """No signer/API/worker container may exist before the flag barrier."""
        if role == "set" and (not self.initializer_finished or self.append_ready):
            raise RuntimeError("native_fixture_initializer_not_exited_before_flag")
        if role not in {"pg", "initialize", "set", "clear"} and not self.append_ready:
            raise RuntimeError("native_fixture_signer_admission_before_flag")

    def initialized(self, receipt: dict) -> None:
        if (
            self.inspect("initialize") is not None
            or "initialize" in self.uncertain
            or receipt.get("status") != "initialized"
        ):
            raise RuntimeError("native_fixture_initializer_exit_receipt_invalid")
        current = (self.root / "authority/checkpoints.bin").lstat()
        if (current.st_dev, current.st_ino) != (
            receipt.get("device"),
            receipt.get("inode"),
        ):
            raise RuntimeError("native_fixture_genesis_receipt_inode_mismatch")
        self.initializer_finished = True

    def seal_layout(self) -> None:
        """Pin fixture inodes before any privileged Docker request."""
        import stat

        for name in ("", "authority", "source", "backend", "mail"):
            path = self.root / name
            value = path.lstat()
            if (
                path.resolve(strict=True) != path
                or not stat.S_ISDIR(value.st_mode)
                or value.st_uid != 1000
                or stat.S_IMODE(value.st_mode) != 0o700
            ):
                raise RuntimeError("native_fixture_private_layout_invalid")
            self.layout[name] = (value.st_dev, value.st_ino)

    def verify_layout(self) -> None:
        if not self.layout:
            raise RuntimeError("native_fixture_layout_not_sealed")
        for name, expected in self.layout.items():
            path = self.root / name
            value = path.lstat()
            if (
                path.resolve(strict=True) != path
                or (value.st_dev, value.st_ino) != expected
            ):
                raise RuntimeError("native_fixture_layout_replaced")

    def inspect(self, role: str) -> str | None:
        if not ROLE.fullmatch(role):
            raise ValueError("native_fixture_role_invalid")
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
            capture_output=True,
            timeout=self.timeout(10),
            env=commands.DOCKER_ENV,
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
            raise RuntimeError("native_fixture_resource_inspect_failed")
        fields = result.stdout.splitlines()
        if len(fields) != 3:
            raise RuntimeError("native_fixture_resource_metadata_invalid")
        identifier, observed, labels = map(json.loads, fields)
        if (
            not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or observed != "/" + name
            or labels.get("io.aqua.run") != self.run
            or labels.get("io.aqua.purpose") != PURPOSE
            or role in self.created
            and identifier != self.created[role]
        ):
            raise RuntimeError("native_fixture_resource_owner_mismatch")
        if role in self.uncertain:
            self.created[role] = identifier
            self.uncertain.discard(role)
        return identifier

    def create(self, role: str) -> str:
        if not ROLE.fullmatch(role) or role in self.attempted:
            raise ValueError("native_fixture_role_reused_or_invalid")
        self.admit(role)
        self.verify_layout()
        self.attempted.append(role)
        self.uncertain.add(role)
        args = [
            "create",
            "--name=" + self.run + "-" + role,
            "--label=io.aqua.run=" + self.run,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--log-driver=none",
            "--pids-limit=128",
            "--restart=no",
            "--stop-timeout=1",
        ]
        image = self.image
        if role == "pg":
            image = POSTGRES
            args += [
                "--user=999:999",
                "--memory=1g",
                "--memory-swap=1g",
                "--cpus=2",
                "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
                "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864",
                "--mount=type=volume,src=" + self.volume + ",dst=/run/aqua-app-db",
                "--env=POSTGRES_HOST_AUTH_METHOD=trust",
            ]
            program = [
                "postgres",
                "-c",
                "listen_addresses=",
                "-c",
                "unix_socket_directories=/var/run/postgresql,/run/aqua-app-db",
            ]
        elif role in {"set", "clear"}:
            device, inode = self.layout["authority"]
            args += [
                "--user=0:0",
                "--memory=128m",
                "--memory-swap=128m",
                "--cpus=1",
                "--cap-add=LINUX_IMMUTABLE",
                "--cap-add=FOWNER",
                "--cap-add=DAC_OVERRIDE",
                "--mount=type=bind,src="
                + str(self.root / "authority")
                + ",dst=/fixture/authority",
                "--env=AQUA_FIXTURE_DEVICE=" + str(device),
                "--env=AQUA_FIXTURE_INODE=" + str(inode),
                "--entrypoint=python",
            ]
            program = ["-c", self.setter, role]
        else:
            memory = "1g" if role == "api" else "256m" if role == "mail" else "128m"
            args += [
                "--user=1000:1000",
                "--memory=" + memory,
                "--memory-swap=" + memory,
                "--cpus=1",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=134217728,mode=1777",
                "--mount=type=bind,src="
                + str(self.root / "source")
                + ",dst=/checks,readonly",
                "--env=PYTHONPATH=/checks/backend:/checks/backend/tests:/checks/tools/checks/retirement_fixture:/checks",
                "--env=PYTHONDONTWRITEBYTECODE=1",
                "--env=PYTHON_DOTENV_DISABLED=1",
                "--workdir=/tmp",
                "--entrypoint=python",
            ]
            if (
                role == "initialize"
                or role in {"crash", "poison"}
                or role.startswith("publish")
            ):
                args += [
                    "--mount=type=bind,src="
                    + str(self.root / "authority")
                    + ",dst=/fixture/authority"
                ]
                if role != "initialize":
                    args += [
                        "--mount=type=volume,src="
                        + self.volume
                        + ",dst=/run/aqua-app-db,readonly"
                    ]
                if role == "crash":
                    args.append("--interactive")
                mode = "publish" if role.startswith("publish") else role
                program = [
                    "-u",
                    "/checks/tools/checks/retirement_fixture/native_roles.py",
                    mode,
                    self.run,
                ]
            else:
                args += [
                    "--mount=type=bind,src="
                    + str(self.root / "backend")
                    + ",dst=/run/aqua-retirement,readonly",
                    "--mount=type=bind,src="
                    + str(self.root / "mail/physical.lock")
                    + ",dst=/run/aqua-retirement/mail-worker.lock,readonly",
                ]
                if role == "api":
                    for name in ("checkpoints.bin", "poison.bin"):
                        args += [
                            "--mount=type=bind,src="
                            + str(self.root / "authority" / name)
                            + ",dst=/run/aqua-retirement/"
                            + name
                            + ",readonly"
                        ]
                    args += [
                        "--mount=type=volume,src="
                        + self.volume
                        + ",dst=/run/aqua-app-db,readonly",
                        "--env=AQUA_RETIREMENT_NATIVE_FIXTURE=true",
                        "--interactive",
                    ]
                    program = [
                        "-u",
                        "/checks/tools/checks/retirement_fixture/integration_cases.py",
                    ]
                else:
                    if role == "mail":
                        info = (self.root / "mail/physical.lock").lstat()
                        args += [
                            "--mount=type=volume,src="
                            + self.volume
                            + ",dst=/run/aqua-app-db,readonly",
                            "--tmpfs=/run/aqua-mail-physical:rw,nosuid,nodev,size=4096,uid=1000,gid=1000,mode=0700",
                            "--mount=type=bind,src="
                            + str(self.root / "mail/physical.lock")
                            + ",dst=/run/aqua-mail-physical/worker.lock,readonly",
                            "--env=ACCOUNT_MAIL_RETIREMENT_LOCK_ENABLED=true",
                            "--env=ACCOUNT_MAIL_PHYSICAL_DEVICE=" + str(info.st_dev),
                            "--env=ACCOUNT_MAIL_PHYSICAL_INODE=" + str(info.st_ino),
                            "--interactive",
                        ]
                    program = [
                        "-u",
                        "/checks/tools/checks/retirement_fixture/native_mail.py",
                        "worker" if role == "mail" else "web",
                        self.run,
                    ]
        identifier = (
            commands.docker(*args, image, *program, timeout=self.timeout(15))
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise RuntimeError("native_fixture_create_unconfirmed")
        self.created[role] = identifier
        if identifier != self.inspect(role):
            raise RuntimeError("native_fixture_create_identity_mismatch")
        self.uncertain.discard(role)
        return identifier

    def remove(self, role: str) -> bool:
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

    def socket(self) -> None:
        self.volume_attempted = True
        self.volume_uncertain = True
        commands.docker(
            "volume",
            "create",
            "--label=io.aqua.run=" + self.run,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--driver=local",
            "--opt=type=tmpfs",
            "--opt=device=tmpfs",
            "--opt=o=size=16m,uid=999,gid=1000,mode=0770",
            self.volume,
            timeout=15,
        )
        metadata = json.loads(
            commands.docker(
                "volume",
                "inspect",
                self.volume,
                "--format={{json .Labels}}",
                timeout=10,
            )
        )
        if (
            metadata.get("io.aqua.run") != self.run
            or metadata.get("io.aqua.purpose") != PURPOSE
        ):
            raise RuntimeError("native_fixture_volume_create_owner_mismatch")
        self.volume_uncertain = False

    def remove_socket(self) -> bool:
        result = subprocess.run(
            [
                "/usr/bin/docker",
                "--host=unix:///var/run/docker.sock",
                "volume",
                "inspect",
                self.volume,
                "--format={{json .Labels}}",
            ],
            capture_output=True,
            timeout=self.timeout(10),
            env=commands.DOCKER_ENV,
        )
        if result.returncode:
            return (
                not self.volume_uncertain
                and result.returncode == 1
                and re.search(
                    rb"(?:no such volume:\s*"
                    + re.escape(self.volume.encode())
                    + rb"|get "
                    + re.escape(self.volume.encode())
                    + rb": no such volume)\s*$",
                    result.stderr.lower(),
                )
                is not None
            )
        labels = json.loads(result.stdout)
        if (
            labels.get("io.aqua.run") != self.run
            or labels.get("io.aqua.purpose") != PURPOSE
        ):
            raise RuntimeError("native_fixture_volume_owner_mismatch")
        self.volume_uncertain = False
        commands.docker("volume", "rm", self.volume, timeout=self.timeout(15))
        return self.remove_socket()
