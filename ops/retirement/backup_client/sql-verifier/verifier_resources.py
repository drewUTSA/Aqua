"""Fresh fixed-name owned containers; no host mount/port or shared database."""

import json
import re

from verifier_process import Budget, DOCKER, Failure, bounded, docker

POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)
PURPOSE = "authority-sql-restore"
RUN = re.compile(r"aqua-authority-verify-[a-f0-9]{24}\Z")
IDENT = re.compile(r"[a-f0-9]{64}\Z")


class Resources:
    def __init__(self, name, image, seconds):
        if not RUN.fullmatch(name) or not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
            raise Failure("verifier_exact_scope_required")
        self.name, self.image = name, image
        self.budget = Budget(seconds)
        self.created, self.attempted = {}, []
        self.uncertain = set()
        self.volume, self.volume_attempted = name + "-socket", False

    def call(self, *args, data=b"", maximum=65536):
        return docker(
            *args, data=data, seconds=self.budget.remaining(), maximum=maximum
        )

    def inspect(self, role):
        if role not in {"pg", "probe"}:
            raise Failure("verifier_role_invalid")
        name = self.name + "-" + role
        code, raw = bounded(
            DOCKER
            + [
                "container",
                "inspect",
                name,
                "--format={{json .Id}}\n{{json .Name}}\n{{json .Config.Labels}}",
            ],
            seconds=self.budget.remaining(10),
        )
        if code == 1 and re.fullmatch(
            rb"(?:\[\]\s*)?(?:error(?: response from daemon)?:\s*)?no such (?:container|object):\s*"
            + re.escape(name.encode())
            + rb"\s*",
            raw.strip().lower(),
        ):
            return None
        if code:
            raise Failure("verifier_container_absence_unconfirmed")
        fields = raw.splitlines()
        if len(fields) != 3:
            raise Failure("verifier_container_metadata_invalid")
        ident, observed, labels = map(json.loads, fields)
        if (
            not isinstance(ident, str)
            or not IDENT.fullmatch(ident)
            or observed != "/" + name
            or labels.get("io.aqua.run") != self.name
            or labels.get("io.aqua.purpose") != PURPOSE
            or role in self.created
            and ident != self.created[role]
        ):
            raise Failure("verifier_container_ownership_mismatch")
        if role in self.uncertain:
            self.created[role] = ident
            self.uncertain.discard(role)
        return ident

    def create(self, role, program):
        if (
            role not in {"pg", "probe"}
            or role in self.attempted
            or self.inspect(role) is not None
        ):
            raise Failure("verifier_fresh_role_required")
        self.attempted.append(role)
        self.uncertain.add(role)
        args = [
            "create",
            "--name=" + self.name + "-" + role,
            "--label=io.aqua.run=" + self.name,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--pull=never",
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges",
            "--pids-limit=128",
            "--restart=no",
            "--log-driver=none",
        ]
        if role == "pg":
            args += [
                "--user=999:999",
                "--memory=1g",
                "--memory-swap=1g",
                "--cpus=2",
                "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
                "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=8388608",
                "--mount=type=volume,src=" + self.volume + ",dst=/run/aqua-app-db",
                "--env=POSTGRES_HOST_AUTH_METHOD=trust",
            ]
            image = POSTGRES
        else:
            args += [
                "--user=1000:1000",
                "--memory=512m",
                "--memory-swap=512m",
                "--cpus=1",
                "--interactive",
                "--tmpfs=/checks:rw,nosuid,nodev,size=100663296,uid=1000,gid=1000,mode=0700",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=8388608,uid=1000,gid=1000,mode=0700",
                "--mount=type=volume,src="
                + self.volume
                + ",dst=/run/aqua-app-db,readonly",
                "--env=PYTHONDONTWRITEBYTECODE=1",
                "--env=PYTHON_DOTENV_DISABLED=1",
                "--entrypoint=python",
            ]
            image = self.image
        ident = self.call(*args, image, *program).decode().strip()
        if not IDENT.fullmatch(ident):
            raise Failure("verifier_create_unconfirmed")
        self.created[role] = ident
        if self.inspect(role) != ident:
            raise Failure("verifier_create_unconfirmed")
        self.uncertain.discard(role)
        return ident

    def socket(self):
        self.volume_attempted = True
        self.call(
            "volume",
            "create",
            "--label=io.aqua.run=" + self.name,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--driver=local",
            "--opt=type=tmpfs",
            "--opt=device=tmpfs",
            "--opt=o=size=16m,uid=999,gid=1000,mode=0770",
            self.volume,
        )
        self.volume_metadata()

    def volume_metadata(self):
        raw = self.call("volume", "inspect", self.volume, "--format={{json .Labels}}")
        labels = json.loads(raw)
        if (
            labels.get("io.aqua.run") != self.name
            or labels.get("io.aqua.purpose") != PURPOSE
        ):
            raise Failure("verifier_volume_owner_mismatch")

    def cleanup(self):
        self.budget = Budget(30)
        remaining = []
        for role in reversed(self.attempted):
            try:
                ident = self.inspect(role)
                if ident:
                    self.call("rm", "--force", ident)
                if role not in self.created:
                    raise Failure("verifier_attempted_create_unresolved")
                # Confirm both the original ID and exact owned name are absent.
                if self.inspect(role) is not None:
                    raise Failure("verifier_container_still_present")
                if (
                    role in self.created
                    and self.call(
                        "ps",
                        "--all",
                        "--no-trunc",
                        "--filter=id=" + self.created[role],
                        "--format={{.ID}}",
                    ).strip()
                ):
                    raise Failure("verifier_original_ID_still_present")
                self.uncertain.discard(role)
            except Exception:
                remaining.append(self.name + "-" + role)
        if self.volume_attempted and not remaining:
            try:
                self.volume_metadata()
                self.call("volume", "rm", self.volume)
                names = self.call(
                    "volume",
                    "ls",
                    "--filter=name=^" + self.volume + "$",
                    "--format={{.Name}}",
                ).splitlines()
                if self.volume.encode() in names:
                    raise Failure("verifier_volume_still_present")
            except Exception:
                remaining.append(self.volume)
        elif self.volume_attempted:
            remaining.append(self.volume)
        return remaining
