"""Fresh native installer QA resources; never production names, data or config.

Proposal only: exact reviewed child-lineage source pins are mandatory. Runtime201
means the exact 200 /app files plus the image's /tmp/requirements-runtime.lock;
the lock is independently pinned and never mounted or substituted by this QA.
No host third-party dependencies; psycopg runs only in the immutable runtime.
"""

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

from prepare_retirement_stage import checked_archive, full_source, put, stage

IMAGE = "sha256:dc50f945f9c20e5c064e4f89a7d83edc30ed75f9bf47018415d936f07171f044"
POSTGRES = (
    "postgres@sha256:3645570cccdfa447589da9f57dd740faa29b30938e861289a5574b6ca6b03826"
)
HBA_SHA256 = "a9efd9abbd930abd4914dd4fbd1c87f4dd1e7363549f5ed96d3daa48c8be1dc1"
RUNTIME_MANIFEST_SHA256 = (
    "74b980666341c0363e90e7fa712e4f5dbfb8ca322cc578a0f1b1b7dc0344c9c5"
)
APP_MANIFEST_SHA256 = "78cf5d8deaf6dabd8328e2c900ab0c6c03c234bd91d39a994341c305d2bdec42"
LOCK_SHA256 = "cad37d805664670589892c601592623d3a2b73e7c80147e3b7695e2a113339a7"
LOCK_BYTES = 88598
BASE = Path("/srv/bank-ai/.check-results")
DOCKER = [
    "/usr/bin/docker",
    "--host=unix:///var/run/docker.sock",
    "--config=/proc/self/fd",
]
ENV = {"PATH": "/usr/bin:/bin", "DOCKER_CONFIG": "/proc/self/fd"}
PURPOSE = "retirement-installer-rehearsal"
LINEAGE_PINS = {
    "ops/retirement/export_resources.py": "a0be58f687330a439c20737b36e6838070f1535118eb09adb016f758a8089518",
    "ops/retirement/install_resources.py": "f6a5e715ce5bb8bef16ce5b378d03231917d6333cf79f1c3724095d9c0339932",
}
ASSETS = {
    "auth/password_blocklist_LICENSE.txt",
    "auth/password_blocklist_provenance.json",
    "auth/password_blocklist_sha256.txt",
}

# The final server starts with the tracked HBA. No trust HBA, published port,
# persistent PGDATA, environment secret or background init server is used.
PG_START = """set -eu
initdb -D /var/lib/postgresql/data --username=postgres --auth-local=peer --auth-host=scram-sha-256 --no-instructions >/dev/null
exec postgres -D /var/lib/postgresql/data -c hba_file=/run/strict-hba.conf -c listen_addresses= -c unix_socket_directories=/var/run/postgresql,/run/aqua-app-db -c password_encryption=scram-sha-256 -c max_connections=40 -c shared_buffers=32MB -c max_wal_size=128MB -c min_wal_size=32MB -c log_statement=none -c log_min_error_statement=panic -c log_min_messages=panic -c logging_collector=off
"""

RUNTIME_PROBE = """import hashlib,json,stat,sys
from pathlib import Path
from storage.migrate import apply
import psycopg
v=json.loads(sys.stdin.buffer.read(131073))
actual={}
for p in Path('/app').rglob('*'):
 s=p.lstat()
 if stat.S_ISDIR(s.st_mode):continue
 if not stat.S_ISREG(s.st_mode) or p.resolve(strict=True)!=p:raise RuntimeError('runtime_nonregular')
 raw=p.read_bytes()
 actual[str(p.relative_to('/app'))]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw)}
if len(actual)!=200 or actual!=v['runtime_files']:raise RuntimeError('runtime_source_mismatch')
lock=Path('/tmp/requirements-runtime.lock');s=lock.lstat()
if not stat.S_ISREG(s.st_mode) or lock.resolve(strict=True)!=lock or s.st_size!=v['lock_bytes']:raise RuntimeError('runtime_lock_metadata')
raw=lock.read_bytes()
if len(raw)!=v['lock_bytes'] or hashlib.sha256(raw).hexdigest()!=v['lock_sha256']:raise RuntimeError('runtime_lock_mismatch')
def connect(role,password,database='aqua_app'):
 return psycopg.connect(host='/run/aqua-app-db',port=5432,dbname=database,user=role,password=password,connect_timeout=3,autocommit=True)
if v['action']=='migrate':
 with connect('aqua_app_migrator',v['password']) as c:
  if apply(c)!=9:raise RuntimeError('schema9_required')
 print(json.dumps({'schema_version':9,'runtime_files':201,'app_files':200,'lock_files':1,'exact_runtime':True}))
elif v['action']=='denials':
 with connect('aqua_app_runtime',v['password']) as c:
  if c.execute('SELECT current_user').fetchone()!=('aqua_app_runtime',):raise RuntimeError('runtime_identity')
  denied=c.execute("SELECT NOT has_database_privilege(current_user,'aqua_retirement','CONNECT') AND NOT pg_has_role(current_user,'aqua_retirement_writer','MEMBER') AND NOT pg_has_role(current_user,'aqua_retirement_checkpoint','MEMBER') AND NOT pg_has_role(current_user,'aqua_retirement_recovery','MEMBER') AND NOT pg_has_role(current_user,'aqua_retirement_backup','MEMBER')").fetchone()==(True,)
  try:c.execute('SET ROLE aqua_retirement_writer')
  except psycopg.errors.InsufficientPrivilege:pass
  else:raise RuntimeError('authority_role_escalation')
 try:connect('aqua_app_runtime',v['wrong_password']).close()
 except psycopg.OperationalError as e:
  # Fixed substring examined only in memory, never emitted to logs/reports.
  wrong='password authentication failed' in str(e)
 else:wrong=False
 try:connect('aqua_app_runtime',v['password'],'aqua_retirement').close()
 except psycopg.OperationalError as e:
  rejected='pg_hba.conf rejects connection' in str(e)
 else:rejected=False
 if not(wrong and denied and rejected):raise RuntimeError('denial_unproven')
 print(json.dumps({'wrong_password_rejected':True,'app_role_authority_denied':True}))
else:raise RuntimeError('probe_action')
"""

# Only the captured fresh installed checkpoint inode can lose APPEND, after all
# scoped holders have exited. This is fixture cleanup, never a repair operation.
CLEAR_APPEND = """import array,fcntl,json,os,stat,sys
from pathlib import Path
v=json.loads(sys.stdin.buffer.read(1025));p=Path('/fixture/checkpoints.bin')
fd=os.open(p,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
try:
 s=os.fstat(fd);n=p.lstat()
 if not(stat.S_ISREG(s.st_mode) and s.st_uid==1000 and s.st_nlink==1 and stat.S_IMODE(s.st_mode)==0o600 and (s.st_dev,s.st_ino)==tuple(v['identity'])==(n.st_dev,n.st_ino)):raise RuntimeError('cleanup_checkpoint_identity')
 flags=array.array('L',[0]);fcntl.ioctl(fd,0x80086601,flags,True);flags[0]&=~0x20;fcntl.ioctl(fd,0x40086602,flags,True)
 check=array.array('L',[0]);fcntl.ioctl(fd,0x80086601,check,True)
 if check[0]&0x20:raise RuntimeError('cleanup_append_remaining')
 os.fsync(fd)
finally:os.close(fd)
print('{"append_cleared":true}')
"""


def canonical(value: dict) -> bytes:
    """Match the operator's public profile serialization exactly."""
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Rehearsal:
    """root is the final public checkout; self.root is the fresh QA run folder."""

    def __init__(self, root: Path, run: str, image: str, source_sha256: str):
        if (
            sys.platform != "linux"
            or os.geteuid() != 1000
            or type(run) is not str
            or not re.fullmatch(r"aqua-retirement-host-[a-f0-9]{24}", run)
            or image != IMAGE
            or not re.fullmatch(r"[a-f0-9]{64}", source_sha256)
        ):
            raise RuntimeError("rehearsal_explicit_native_scope_required")
        from ops.retirement.operator_scope import Scope

        self.source_root, self.run, self.image = root, run, image
        self.source_sha256 = source_sha256
        self.scope = Scope(run)
        self.root, self.stage = self.scope.parent, self.scope.parent / "stage"
        if self.root != BASE / run or root.resolve(strict=True) != root:
            raise RuntimeError("rehearsal_source_or_scope_invalid")
        self.ids: dict[str, str] = {}
        self.attempted: list[str] = []
        self.uncertain: set[str] = set()
        self.volume_created = self.root_created = False
        self.volume_attempted = False
        self.root_identity = None
        self.passwords: dict[str, str] = {}
        self.child_ids: dict[str, tuple] = {}
        self.checkpoint_identity: tuple[int, int] | None = None
        self.deadline = time.monotonic() + 300

    def command(self, *args: str, data=None, seconds=15, limit=262144) -> bytes:
        """Suppress all raw diagnostics, particularly SQL and private stdin."""
        remaining = min(seconds, self.deadline - time.monotonic())
        if remaining <= 0:
            raise RuntimeError("rehearsal_deadline")
        result = subprocess.run(
            [*DOCKER, *args],
            input=data,
            capture_output=True,
            timeout=remaining,
            env=ENV,
            close_fds=True,
            check=False,
        )
        if result.returncode or len(result.stdout) > limit:
            raise RuntimeError("rehearsal_container_command_failed")
        return result.stdout

    def inspect(self, identifier: str):
        """Absence is confirmed only by the daemon's exact requested identity."""
        remaining = min(10, self.deadline - time.monotonic())
        if remaining <= 0:
            raise RuntimeError("rehearsal_deadline")
        result = subprocess.run(
            [
                *DOCKER,
                "container",
                "inspect",
                identifier,
                "--format={{json .Id}}\n{{json .Name}}\n{{json .Config.Labels}}\n{{json .Image}}\n{{json .Mounts}}",
            ],
            capture_output=True,
            timeout=remaining,
            env=ENV,
            close_fds=True,
            check=False,
        )
        if (
            result.returncode == 1
            and result.stdout in {b"", b"\n", b"[]\n"}
            and re.search(
                rb"no such (?:object|container):\s*"
                + re.escape(identifier.encode())
                + rb"\s*$",
                result.stderr.lower(),
            )
        ):
            return None
        if result.returncode or len(result.stdout) > 16384:
            raise RuntimeError("rehearsal_identity_uncertain")
        fields = result.stdout.splitlines()
        if len(fields) != 5:
            raise RuntimeError("rehearsal_identity_shape")
        return tuple(map(json.loads, fields))

    def owned(self, role: str):
        observed = self.inspect(self.run + "-" + role)
        if observed is None:
            if role in self.ids and self.inspect(self.ids[role]) is not None:
                raise RuntimeError("rehearsal_name_identity_changed")
            return None
        identifier, name, labels, image, _ = observed
        expected_image = self.pg_image if role == "pg" else self.image
        if (
            not re.fullmatch(r"[a-f0-9]{64}", identifier)
            or name != "/" + self.run + "-" + role
            or labels.get("io.aqua.run") != self.run
            or labels.get("io.aqua.role") != role
            or labels.get("io.aqua.purpose") != PURPOSE
            or image != expected_image
            or role in self.ids
            and self.ids[role] != identifier
        ):
            raise RuntimeError("rehearsal_wrong_resource_owner")
        self.ids[role] = identifier
        self.uncertain.discard(role)
        return identifier

    def create(
        self,
        role: str,
        *,
        image=None,
        extra=(),
        argv=(),
        user="1000:1000",
        memory="128m",
        pids=32,
    ):
        """Track create uncertainty before talking to Docker; never adopt names."""
        if role in self.attempted or self.inspect(self.run + "-" + role) is not None:
            raise RuntimeError("rehearsal_resource_collision")
        self.attempted.append(role)
        self.uncertain.add(role)
        raw = self.command(
            "container",
            "create",
            "--pull=never",
            "--name=" + self.run + "-" + role,
            "--label=io.aqua.run=" + self.run,
            "--label=io.aqua.role=" + role,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--network=none",
            "--read-only",
            "--cap-drop=ALL",
            "--security-opt=no-new-privileges:true",
            "--cpus=1",
            "--memory=" + memory,
            "--memory-swap=" + memory,
            "--pids-limit=" + str(pids),
            "--restart=no",
            "--log-driver=none",
            "--no-healthcheck",
            "--stop-timeout=1",
            "--user=" + user,
            *extra,
            image or self.image,
            *argv,
        )
        identifier = raw.decode().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", identifier):
            raise RuntimeError("rehearsal_create_uncertain")
        self.ids[role] = identifier
        if self.owned(role) != identifier:
            raise RuntimeError("rehearsal_create_identity_mismatch")
        return identifier

    def remove(self, role: str) -> None:
        identifier = self.owned(role)
        if identifier is None and role in self.uncertain and role not in self.ids:
            raise RuntimeError("rehearsal_unresolved_create_identity")
        if identifier is not None:
            self.command("container", "rm", "--force", identifier)
            if (
                self.inspect(identifier) is not None
                or self.inspect(self.run + "-" + role) is not None
            ):
                raise RuntimeError("rehearsal_remove_uncertain")
        self.uncertain.discard(role)

    def once(
        self, role: str, program: str, data: dict, *, extra=(), user="1000:1000"
    ) -> dict:
        """No private input enters argv or Docker configuration/environment."""
        # Rejected reuse must not clean up a role owned by an earlier invocation.
        if role in self.attempted:
            raise RuntimeError("rehearsal_resource_collision")
        try:
            identifier = self.create(
                role,
                extra=(
                    "--interactive",
                    "--workdir=/app",
                    "--entrypoint=python",
                    *extra,
                ),
                argv=("-E", "-s", "-B", "-c", program),
                user=user,
            )
            raw = self.command(
                "container",
                "start",
                "--attach",
                "--interactive",
                identifier,
                data=canonical(data),
                seconds=45,
                limit=4096,
            )
            if self.command(
                "inspect",
                identifier,
                "--format={{json .State.Running}}\n{{json .State.ExitCode}}",
            ).splitlines() != [b"false", b"0"]:
                raise RuntimeError("rehearsal_probe_exit")
            return json.loads(raw)
        finally:
            if role in self.attempted:
                self.remove(role)

    def prepare(self) -> dict:
        """Create one new app-only cluster, never reuse a database or QA root."""
        from ops.retirement.install import SOURCE_NAMES

        archive = full_source(self.source_root)
        cache = checked_archive(archive, self.source_sha256)
        if any(
            hashlib.sha256(cache[name]).hexdigest() != pin
            for name, pin in LINEAGE_PINS.items()
        ):
            raise RuntimeError("rehearsal_reviewed_child_lineage_required")
        hba = cache["ops/appdb/pg_hba.conf"]
        if hashlib.sha256(hba).hexdigest() != HBA_SHA256:
            raise RuntimeError("rehearsal_exact_strict_HBA_required")
        self.runtime_files = {
            name.removeprefix("backend/"): {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "bytes": len(raw),
            }
            for name, raw in cache.items()
            if name.startswith("backend/")
            and not name.startswith("backend/tests/")
            and (
                Path(name).suffix in {".py", ".sql"}
                or name.removeprefix("backend/") in ASSETS
            )
        }
        if (
            len(self.runtime_files) != 200
            or hashlib.sha256(canonical(self.runtime_files)).hexdigest()
            != APP_MANIFEST_SHA256
        ):
            raise RuntimeError("rehearsal_exact_app200_manifest_required")
        if (
            self.command("image", "inspect", self.image, "--format={{.Id}}").strip()
            != self.image.encode()
        ):
            raise RuntimeError("rehearsal_runtime_image_changed")
        self.pg_image = (
            self.command("image", "inspect", POSTGRES, "--format={{.Id}}")
            .decode()
            .strip()
        )
        if not re.fullmatch(r"sha256:[a-f0-9]{64}", self.pg_image):
            raise RuntimeError("rehearsal_postgres_identity")
        # Exclusive root creation happens only after public source/image checks.
        if BASE.resolve(strict=True) != BASE or not BASE.is_dir():
            raise RuntimeError("rehearsal_base_not_canonical")
        self.root.mkdir(mode=0o700)
        self.root_created = True
        os.chmod(self.root, 0o700)
        self.scope.validate()
        info = self.root.lstat()
        self.root_identity = (info.st_dev, info.st_ino)
        code_pin = stage(self.source_root, self.stage, SOURCE_NAMES, cached=cache)
        self.scope.mail.mkdir(mode=0o700)
        os.chmod(self.scope.mail, 0o700)
        put(self.scope.mail / ".launcher.lock", b"")
        put(self.scope.mail / "physical.lock", b"")
        schedule = ("no scheduler installed for " + self.run + "\n").encode()
        put(self.root / "schedule.absent", schedule)
        hba_path = self.root / "strict-hba.conf"
        put(hba_path, hba)
        # Public bytes must be readable to UID999 after file-only read-only bind.
        os.chmod(hba_path, 0o644)
        volumes = self.command(
            "volume", "ls", "--quiet", "--filter=name=^" + self.scope.socket + "$"
        ).splitlines()
        if volumes:
            raise RuntimeError("rehearsal_socket_collision")
        self.volume_attempted = True
        self.command(
            "volume",
            "create",
            "--label=io.aqua.run=" + self.run,
            "--label=io.aqua.purpose=" + PURPOSE,
            "--driver=local",
            "--opt=type=tmpfs",
            "--opt=device=tmpfs",
            "--opt=o=size=16777216,uid=999,gid=999,mode=0777",
            self.scope.socket,
        )
        self.volume_created = True
        self.verify_volume()
        pg = self.create(
            "pg",
            image=POSTGRES,
            user="999:999",
            memory="512m",
            pids=64,
            extra=(
                "--entrypoint=/bin/sh",
                "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=536870912,uid=999,gid=999,mode=0700",
                "--tmpfs=/var/run/postgresql:rw,nosuid,nodev,size=16777216,uid=999,gid=999",
                "--tmpfs=/tmp:rw,nosuid,nodev,size=67108864",
                "--mount=type=volume,src="
                + self.scope.socket
                + ",dst=/run/aqua-app-db",
                "--mount=type=bind,src="
                + str(hba_path)
                + ",dst=/run/strict-hba.conf,readonly",
            ),
            argv=("-c", PG_START),
        )
        self.command("start", pg)
        until = min(self.deadline, time.monotonic() + 45)
        while True:
            try:
                if (
                    self.command("exec", pg, "cat", "/proc/1/comm").strip()
                    != b"postgres"
                ):
                    raise RuntimeError("rehearsal_postgres_starting")
                self.command(
                    "exec",
                    pg,
                    "pg_isready",
                    "-h",
                    "/var/run/postgresql",
                    "-U",
                    "postgres",
                )
                break
            except RuntimeError:
                if time.monotonic() >= until:
                    raise RuntimeError("rehearsal_postgres_not_ready") from None
                time.sleep(0.25)
        self.passwords = {
            role: secrets.token_urlsafe(32)
            for role in ("migrator", "runtime", "backup")
        }
        prefix = b"".join(
            ("\\set " + role + "_password '" + value + "'\n").encode()
            for role, value in self.passwords.items()
        )
        self.command(
            "exec",
            "-i",
            pg,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-At",
            data=prefix + cache["backend/migrations/bootstrap.psql"],
            seconds=30,
        )
        result = self.once(
            "migrate",
            RUNTIME_PROBE,
            {
                "action": "migrate",
                "runtime_files": self.runtime_files,
                "lock_bytes": LOCK_BYTES,
                "lock_sha256": LOCK_SHA256,
                "password": self.passwords["migrator"],
            },
            extra=(self.socket_mount(),),
        )
        if result != {
            "schema_version": 9,
            "runtime_files": 201,
            "app_files": 200,
            "lock_files": 1,
            "exact_runtime": True,
        }:
            raise RuntimeError("rehearsal_app_migration_unproven")
        backend = self.create("stopped-backend", extra=("--entrypoint=/bin/true",))
        plan = {
            "schemaVersion": 1,
            "runtime_image": self.image,
            "source_sha256": self.source_sha256,
            "backend_id": backend,
            "backend_image": self.image,
            "database_id": pg,
            "database_image": self.pg_image,
            "paused_cron_sha256": hashlib.sha256(schedule).hexdigest(),
        }
        put(self.scope.plan, canonical(plan))
        profile = {
            "schemaVersion": 1,
            "runtime_image": self.image,
            "source_sha256": self.source_sha256,
            "plan_sha256": hashlib.sha256(canonical(plan)).hexdigest(),
            "code_manifest_sha256": code_pin,
        }
        put(self.scope.install_profile, canonical(profile))
        return {
            "install_profile_sha256": hashlib.sha256(canonical(profile)).hexdigest(),
            "code_manifest_sha256": code_pin,
            "source_sha256": self.source_sha256,
            "child_ownership_linked": True,
        }

    def socket_mount(self) -> str:
        return (
            "--mount=type=volume,src="
            + self.scope.socket
            + ",dst=/run/aqua-app-db,readonly"
        )

    def probe_denials(self) -> dict:
        """Require good authentication as a control before each negative claim."""
        self.scope.validate()
        if not self.passwords or self.owned("pg") is None:
            raise RuntimeError("rehearsal_cluster_missing")
        return self.once(
            "denials",
            RUNTIME_PROBE,
            {
                "action": "denials",
                "runtime_files": self.runtime_files,
                "lock_bytes": LOCK_BYTES,
                "lock_sha256": LOCK_SHA256,
                "password": self.passwords["runtime"],
                "wrong_password": secrets.token_urlsafe(32),
            },
            extra=(self.socket_mount(),),
        )

    def prepare_recovery(self, head: dict, code_pin: str) -> str:
        """Create one QA-only app-only recovery profile after keeper release.

        Only the existing recovery-role DSN is copied. HMAC/signing key bytes
        remain in the installed fixture and never enter this child profile.
        """
        from ops.retirement.operator_files import read, write_once

        self.scope.validate()
        self.capture_installed_checkpoint()
        public_names = {
            "schemaVersion",
            "installation_id",
            "identity_key_id",
            "key_commitment",
            "public_key",
            "runtime_image",
            "source_sha256",
        }
        if (
            not public_names <= set(head)
            or type(head.get("schemaVersion")) is not int
            or head["schemaVersion"] != 1
            or head["runtime_image"] != self.image
            or head["source_sha256"] != self.source_sha256
            or type(head.get("sequence")) is not int
            or head["sequence"] != 0
            or head.get("event_digest") != "0" * 64
            or not re.fullmatch(r"[a-f0-9]{64}", code_pin)
            or not re.fullmatch(r"[a-f0-9]{64}", head.get("protected_chain_sha256", ""))
            or self.owned("pg") is None
            or self.owned("stopped-backend") is None
        ):
            raise RuntimeError("rehearsal_genesis_recovery_context_invalid")
        # These are all scoped owner-only files. This adapter never reads either
        # identity.key or signing.key, and creates no authority credential.
        plan = read(self.scope.plan)
        fence = read(self.stage / "restore_session_fence.sql", 131072)
        role_dsn = read(self.scope.private / "operator/export/recovery.dsn", 512)
        if not re.fullmatch(
            rb"postgresql://aqua_retirement_recovery:[A-Za-z0-9_-]{43}@/aqua_retirement\?host=/run/aqua-app-db&port=5432&sslmode=disable",
            role_dsn,
        ):
            raise RuntimeError("rehearsal_recovery_role_DSN_invalid")
        destination = self.scope.private / "operator/recovery"
        destination.mkdir(mode=0o700)
        os.chmod(destination, 0o700)
        public = canonical({name: head[name] for name in public_names})
        app_dsn = (
            "host=/run/aqua-app-db port=5432 dbname=aqua_app "
            "user=aqua_app_runtime password="
            + self.passwords["runtime"]
            + " sslmode=disable"
        ).encode()
        for name, raw in {
            "verification.json": public,
            "app.dsn": app_dsn,
            "recovery.dsn": role_dsn,
            "checkpoints.bin": b"",
            "mail-worker.lock": b"",
        }.items():
            write_once(destination / name, raw)
        profile = canonical(
            {
                "schemaVersion": 1,
                "runtime_image": self.image,
                "source_sha256": self.source_sha256,
                "plan_sha256": hashlib.sha256(plan).hexdigest(),
                "code_manifest_sha256": code_pin,
                "verification_sha256": hashlib.sha256(public).hexdigest(),
                "fence_sha256": hashlib.sha256(fence).hexdigest(),
            }
        )
        write_once(self.scope.private / "operator/recovery.json", profile)
        return hashlib.sha256(profile).hexdigest()

    def verify_volume(self) -> None:
        value = json.loads(
            self.command(
                "volume",
                "inspect",
                self.scope.socket,
                "--format={{json .}}",
                limit=4096,
            )
        )
        if (
            value.get("Name") != self.scope.socket
            or value.get("Driver") != "local"
            or value.get("Labels")
            != {"io.aqua.run": self.run, "io.aqua.purpose": PURPOSE}
            or value.get("Options")
            != {
                "type": "tmpfs",
                "device": "tmpfs",
                "o": "size=16777216,uid=999,gid=999,mode=0777",
            }
        ):
            raise RuntimeError("rehearsal_socket_owner_changed")

    def child_mount_sets(self, role: str) -> tuple[frozenset, ...]:
        """Only exact installer/export/recovery mounts are removable here."""
        root = self.scope.private

        def bind(source: Path, target: str, writable: bool = False):
            return ("bind", str(source), target, writable)

        socket = ("volume", self.scope.socket, "/run/aqua-app-db", False)
        fixed = {
            "materialize": {bind(root, "/home/ben2004/.aqua-runtime/retirement", True)},
            "initializer": {
                bind(root / "initializer", "/run/aqua-retirement-initializer"),
                bind(root / "authority", "/run/aqua-retirement-authority", True),
            },
            "setter": {
                bind(root / "authority", "/run/aqua-retirement-provisioning", True)
            },
            "genesis_ack": {
                bind(root / "authority", "/run/aqua-retirement", True),
                bind(root / "host", "/run/aqua-retirement-host"),
                socket,
            },
            "dump": {socket},
            "recovery": {
                bind(root / "operator/recovery", "/run/aqua-retirement"),
                bind(
                    root / "authority/checkpoints.bin",
                    "/run/aqua-retirement/checkpoints.bin",
                ),
                bind(
                    self.scope.mail / "physical.lock",
                    "/run/aqua-retirement/mail-worker.lock",
                ),
                socket,
            },
        }
        if role in fixed:
            return (frozenset(fixed[role]),)
        if role != "peer":
            raise RuntimeError("rehearsal_child_role_invalid")
        shared = {
            bind(
                root / "authority/checkpoints.bin",
                "/run/aqua-retirement-backup/checkpoints.bin",
            ),
            bind(root / "operator/code", "/operator"),
        }
        return (
            frozenset(
                shared | {bind(root / "operator/public", "/run/aqua-retirement-backup")}
            ),
            frozenset(
                shared
                | {
                    bind(root / "operator/export", "/run/aqua-retirement-backup"),
                    bind(
                        root / "backend/identity.key",
                        "/run/aqua-retirement-backup/identity.key",
                    ),
                    bind(
                        root / "host/signing.key",
                        "/run/aqua-retirement-backup/signing.key",
                    ),
                    socket,
                }
            ),
        )

    def child_identity(self, identifier: str) -> tuple | None:
        """QA linkage alone is insufficient: bind nonce, image, mounts and ID."""
        value = self.inspect(identifier)
        if value is None:
            return None
        actual, name, labels, image, mounts = value
        match = re.fullmatch(
            r"/(aqua-retirement-(install|archive|recovery)-[a-f0-9]{32})-(materialize|initializer|setter|genesis_ack|peer|dump|recovery)",
            name,
        )
        if (
            not match
            or actual != identifier
            or labels.get("io.aqua.qa-run") != self.run
            or labels.get("io.aqua.run") != match[1]
        ):
            raise RuntimeError("rehearsal_child_lineage_invalid")
        family, role = match[2], match[3]
        allowed_roles = {
            "install": {"materialize", "initializer", "setter", "genesis_ack"},
            "archive": {"peer", "dump"},
            "recovery": {"recovery"},
        }
        purpose = (
            "retirement-offline-recovery"
            if family == "recovery"
            else "retirement-" + family + "-operator"
        )
        if (
            labels.get("io.aqua.purpose") != purpose
            or role not in allowed_roles[family]
            or image != (self.pg_image if role == "dump" else self.image)
        ):
            raise RuntimeError("rehearsal_child_image_role_invalid")
        normalized = frozenset(
            (
                item.get("Type"),
                (
                    item.get("Name")
                    if item.get("Type") == "volume"
                    else item.get("Source")
                ),
                item.get("Destination"),
                item.get("RW"),
            )
            for item in mounts
        )
        if len(normalized) != len(mounts) or normalized not in self.child_mount_sets(
            role
        ):
            raise RuntimeError("rehearsal_child_mounts_invalid")
        identity = (actual, name, labels, image, normalized)
        if identifier in self.child_ids and identity != self.child_ids[identifier]:
            raise RuntimeError("rehearsal_child_identity_changed")
        self.child_ids[identifier] = identity
        return identity

    def remove_children(self) -> None:
        """Reap only exact reviewed QA children; never select purpose prefixes."""
        identifiers = (
            self.command(
                "ps",
                "--all",
                "--quiet",
                "--no-trunc",
                "--filter=label=io.aqua.qa-run=" + self.run,
                limit=65536,
            )
            .decode()
            .split()
        )
        if len(identifiers) > 32 or any(
            not re.fullmatch(r"[a-f0-9]{64}", value) for value in identifiers
        ):
            raise RuntimeError("rehearsal_child_inventory_invalid")
        for identifier in identifiers:
            if identifier in self.ids.values():
                continue
            value = self.child_identity(identifier)
            if value is not None:
                # Repeat immediately before mutation, using the same immutable ID.
                if self.child_identity(identifier) != value:
                    raise RuntimeError("rehearsal_child_identity_changed")
                self.command("container", "rm", "--force", identifier)
                if (
                    self.inspect(identifier) is not None
                    or self.inspect(value[1].removeprefix("/")) is not None
                ):
                    raise RuntimeError("rehearsal_child_absence_unconfirmed")
        if self.command(
            "ps",
            "--all",
            "--quiet",
            "--no-trunc",
            "--filter=label=io.aqua.qa-run=" + self.run,
            limit=65536,
        ).strip():
            raise RuntimeError("rehearsal_child_inventory_not_empty")

    def unknown_holders(self) -> list[str]:
        """Inspect only mounts/identity; do not read environment or prune prefixes."""
        holders = []
        for identifier in (
            self.command("ps", "--all", "--quiet", "--no-trunc", limit=65536)
            .decode()
            .split()
        ):
            if identifier in self.ids.values():
                continue
            value = self.inspect(identifier)
            if value is None:
                continue
            for mount in value[4]:
                source = mount.get("Source", "")
                if (
                    mount.get("Name") == self.scope.socket
                    or source == str(self.root)
                    or source.startswith(str(self.root) + "/")
                ):
                    holders.append(identifier)
                    break
        return holders

    def capture_installed_checkpoint(self) -> None:
        """Pin after the verified installed receipt, never first adopt at cleanup."""
        self.scope.validate()
        path = self.scope.private / "authority/checkpoints.bin"
        meta = path.lstat()
        if (
            path.resolve(strict=True) != path
            or not stat.S_ISREG(meta.st_mode)
            or meta.st_uid != 1000
            or meta.st_nlink != 1
            or stat.S_IMODE(meta.st_mode) != 0o600
        ):
            raise RuntimeError("rehearsal_installed_checkpoint_invalid")
        identity = (meta.st_dev, meta.st_ino)
        if (
            self.checkpoint_identity is not None
            and self.checkpoint_identity != identity
        ):
            raise RuntimeError("rehearsal_installed_checkpoint_changed")
        self.checkpoint_identity = identity

    def cleanup(self) -> dict:
        """Never remove fixtures while an actual operator still owns its locks."""
        import fcntl

        try:
            with ExitStack() as locks:
                if self.root_created:
                    self.scope.validate()
                    for path in (
                        self.scope.operation,
                        self.scope.mail / ".launcher.lock",
                        self.scope.mail / "physical.lock",
                        self.scope.private / "host/publisher.lock",
                    ):
                        if not path.exists():
                            continue
                        fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
                        locks.callback(os.close, fd)
                        opened, named = os.fstat(fd), path.lstat()
                        if (
                            path.resolve(strict=True) != path
                            or not stat.S_ISREG(opened.st_mode)
                            or opened.st_uid != 1000
                            or opened.st_nlink != 1
                            or stat.S_IMODE(opened.st_mode) != 0o600
                            or opened.st_size != 0
                            or (opened.st_dev, opened.st_ino)
                            != (named.st_dev, named.st_ino)
                        ):
                            raise RuntimeError("rehearsal_cleanup_lock_invalid")
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self.cleanup_owned()
        except (OSError, RuntimeError, subprocess.TimeoutExpired):
            return {
                "complete": False,
                "reason": "cleanup_operator_still_active_or_uncertain",
            }

    def _sweep_registered(self, start: int) -> bool:
        """Attempt only roles newly registered by this cleanup invocation."""
        complete = True
        roles = tuple(self.attempted[start:])
        for role in reversed(roles):
            try:
                self.remove(role)
            except BaseException:  # noqa: BLE001
                # Cleanup cancellation/decoding errors cannot become success or
                # skip another exact-owned role. The caller retains red status.
                complete = False
        return complete and not any(role in self.uncertain for role in roles)

    def _clear_checkpoint(self, checkpoint: Path) -> bool:
        """Reserve a second owned-role sweep inside the original cleanup budget."""
        start = len(self.attempted)
        original_deadline = self.deadline
        append_confirmed = False
        swept = False
        try:
            # Preserve 15 seconds of the existing 90-second cleanup budget.
            self.deadline = original_deadline - 15
            meta = checkpoint.lstat()
            if self.checkpoint_identity != (meta.st_dev, meta.st_ino):
                raise RuntimeError("rehearsal_cleanup_checkpoint_not_previously_pinned")
            result = self.once(
                "cleanup-append",
                CLEAR_APPEND,
                {"identity": list(self.checkpoint_identity)},
                user="0:0",
                extra=(
                    "--cap-add=DAC_OVERRIDE",
                    "--cap-add=FOWNER",
                    "--cap-add=LINUX_IMMUTABLE",
                    "--mount=type=bind,src=" + str(checkpoint.parent) + ",dst=/fixture",
                ),
            )
            append_confirmed = result == {"append_cleared": True}
        except BaseException:  # noqa: BLE001
            # Malformed results, lost create replies, failed first removal and
            # cancellation all remain red even if the second sweep succeeds.
            append_confirmed = False
        finally:
            self.deadline = min(original_deadline, time.monotonic() + 15)
            try:
                swept = self._sweep_registered(start)
            finally:
                self.deadline = original_deadline
        return append_confirmed and swept

    def cleanup_owned(self) -> dict:
        """No green result if ownership, APPEND or any physical removal is unsure."""
        self.deadline = time.monotonic() + 90
        errors = []
        if self.root_created:
            try:
                self.scope.validate()
                info = self.root.lstat()
                if (info.st_dev, info.st_ino) != self.root_identity:
                    raise RuntimeError("rehearsal_root_replaced")
                self.remove_children()
                if self.unknown_holders():
                    raise RuntimeError("rehearsal_unlinked_child_holder")
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return {
                    "complete": False,
                    "reason": "fixture_scope_or_children_uncertain",
                }
        for role in reversed(tuple(self.attempted)):
            try:
                self.remove(role)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                errors.append("container_removal_unconfirmed")
        if errors or self.uncertain:
            return {"complete": False, "reason": "owned_container_removal_uncertain"}
        checkpoint = self.scope.private / "authority/checkpoints.bin"
        if (
            self.root_created
            and checkpoint.exists()
            and not self._clear_checkpoint(checkpoint)
        ):
            return {"complete": False, "reason": "APPEND_cleanup_uncertain"}
        if self.volume_attempted:
            try:
                self.verify_volume()
                self.command("volume", "rm", self.scope.socket)
                if self.command(
                    "volume",
                    "ls",
                    "--quiet",
                    "--filter=name=^" + self.scope.socket + "$",
                ).strip():
                    raise RuntimeError("rehearsal_socket_absence_unconfirmed")
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                return {"complete": False, "reason": "socket_removal_uncertain"}
        if self.root_created:
            try:
                # Refuse symlinks/hardlinks/unexpected owners anywhere, then delete
                # only this captured exclusive QA tree, deepest first.
                paths = list(self.root.rglob("*"))
                for path in paths:
                    info = path.lstat()
                    if (
                        path.resolve(strict=True) != path
                        or info.st_uid != 1000
                        or not (
                            stat.S_ISREG(info.st_mode)
                            and info.st_nlink == 1
                            or stat.S_ISDIR(info.st_mode)
                        )
                    ):
                        raise RuntimeError("rehearsal_cleanup_tree_not_owned")
                for path in sorted(
                    paths, key=lambda item: len(item.parts), reverse=True
                ):
                    if path.is_dir():
                        path.rmdir()
                    else:
                        path.unlink()
                self.root.rmdir()
                if self.root.exists():
                    raise RuntimeError("rehearsal_root_absence_unconfirmed")
            except (OSError, RuntimeError):
                return {"complete": False, "reason": "private_files_removal_uncertain"}
        self.passwords.clear()
        return {
            "complete": True,
            "containers_absent": True,
            "socket_absent": True,
            "private_root_absent": True,
            "production_touched": False,
        }
