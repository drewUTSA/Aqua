"""PRIVATE host launcher. No installation, cron, credentials or key reads now.

Default prints a plan. Production --execute remains disabled until a reviewed
source-manifest hash replaces PENDING below after actual storage/recovery gates.
Only the future separate host publisher receives the signing-key directory.
"""

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import signal
import stat
import subprocess
import sys
import time

PRIVATE = Path("/home/ben2004/.aqua-runtime/retirement")
IMAGE = "sha256:1f541b30b479760c32a7a7d35adc2cfad4082ab465157510541ac7e49a0c9e2f"
REVIEWED_CODE_SHA256 = "PENDING_STORAGE_AND_RECOVERY_PROOF"
NAME = "aqua-retirement-publisher"
PURPOSE = "retirement-publisher"
SOCKET_VOLUME = "aqua_app_sockets"
FILES = (
    "host-sources/retirement_host.py",
    "backend-sources/retirement/checkpoint.py",
    "backend-sources/retirement/fingerprints.py",
    "backend-sources/retirement/interlock.py",
    "backend-sources/retirement/publisher.py",
)
COMMAND_ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/nonexistent",
    "DOCKER_CONFIG": "/nonexistent",
    "LANG": "C.UTF-8",
}
IDENT = re.compile(r"[a-f0-9]{64}\Z")


class Unavailable(RuntimeError):
    def __init__(self):
        super().__init__("retirement_publisher_launcher_unavailable")


def directory(path):
    value = path.lstat()
    if (
        not path.is_absolute()
        or path.resolve(strict=True) != path
        or not stat.S_ISDIR(value.st_mode)
        or value.st_uid != 1000
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise Unavailable()


def file_fd(path, limit, *, exact=None):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    try:
        value = os.fstat(fd)
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != 1000
            or value.st_nlink != 1
            or stat.S_IMODE(value.st_mode) != 0o600
            or not 0 < value.st_size <= limit
            or exact is not None
            and value.st_size != exact
        ):
            raise Unavailable()
        named = path.lstat()
        if path.resolve(strict=True) != path or (named.st_dev, named.st_ino) != (
            value.st_dev,
            value.st_ino,
        ):
            raise Unavailable()
        return fd
    except BaseException:
        os.close(fd)
        raise


def code_ready(root, expected):
    directory(root)
    fd = file_fd(root / "code-manifest.json", 16384)
    with os.fdopen(fd, "rb") as stream:
        raw = stream.read(16385)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise Unavailable()
    values = json.loads(raw)
    if type(values) is not dict or set(values) != set(FILES):
        raise Unavailable()
    for name in FILES:
        path = root / name
        directory(path.parent)
        fd = file_fd(path, 131072)
        with os.fdopen(fd, "rb") as stream:
            body = stream.read(131073)
        if hashlib.sha256(body).hexdigest() != values[name]:
            raise Unavailable()


@contextmanager
def singleton(root):
    import fcntl

    path = root / "publisher.lock"
    fd = os.open(path, os.O_RDWR | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        value = os.fstat(fd)
        named = path.lstat()
        if (
            not stat.S_ISREG(value.st_mode)
            or value.st_uid != 1000
            or value.st_nlink != 1
            or stat.S_IMODE(value.st_mode) != 0o600
            or (named.st_dev, named.st_ino) != (value.st_dev, value.st_ino)
        ):
            raise Unavailable()
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            yield True
    finally:
        os.close(fd)


def append_flag(path):
    import array
    import fcntl

    fd = file_fd(path, 64 * 1024 * 1024)
    try:
        flags = array.array("L", [0])
        fcntl.ioctl(fd, 0x80086601, flags, True)
        if not flags[0] & 0x20:
            raise Unavailable()
    finally:
        os.close(fd)


class Docker:
    def __init__(self):
        self.started = time.monotonic()
        self.work_deadline = self.started + 50
        self.deadline = self.started + 55

    def call(self, *args, cleanup=False, timeout=8):
        remaining = (
            self.deadline if cleanup else self.work_deadline
        ) - time.monotonic()
        if remaining <= 0:
            raise Unavailable()
        try:
            result = subprocess.run(
                [
                    "/usr/bin/docker",
                    "--host=unix:///var/run/docker.sock",
                    "--config=/nonexistent",
                    *args,
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                timeout=min(timeout, remaining),
                env=COMMAND_ENV,
                cwd="/",
                close_fds=True,
            )
        except subprocess.TimeoutExpired:
            raise Unavailable() from None
        if result.returncode or len(result.stdout) > 65536:
            raise Unavailable()
        return result.stdout.decode("utf-8").strip()

    def ids(self, *filters, cleanup=False):
        args = ["container", "ls", "--all", "--no-trunc"]
        for value in filters:
            args += ["--filter", value]
        raw = self.call(*args, "--format", "{{.ID}}", cleanup=cleanup)
        values = raw.splitlines() if raw else []
        if len(values) > 64 or any(not IDENT.fullmatch(value) for value in values):
            raise Unavailable()
        return values

    def owned(self, nonce, *, cleanup=False):
        values = self.ids("name=^/" + NAME + "$", cleanup=cleanup)
        if not values:
            return None
        if len(values) != 1:
            raise Unavailable()
        raw = self.call(
            "container",
            "inspect",
            "--format",
            "{{.Id}}\n{{.Name}}\n{{json .Config.Labels}}",
            values[0],
            cleanup=cleanup,
        )
        lines = raw.splitlines()
        if (
            len(lines) != 3
            or lines[:2] != [values[0], "/" + NAME]
            or json.loads(lines[2]).get("io.aqua.purpose") != PURPOSE
            or json.loads(lines[2]).get("io.aqua.run") != nonce
        ):
            raise Unavailable()
        return values[0]

    def clean(self, nonce, expected):
        try:
            actual = self.owned(nonce, cleanup=True)
            if actual is None:
                return expected is not None and not self.ids(
                    "id=" + expected, cleanup=True
                )
            if expected is not None and actual != expected:
                return False
            try:
                self.call("container", "rm", "--force", actual, cleanup=True)
            except Unavailable:
                pass
            return not self.ids("id=" + actual, cleanup=True)
        except Exception:
            return False


VERIFY_CODE = r"""import hashlib,json,os,stat,sys,types
from pathlib import Path
root=Path('/publisher');assert root.resolve()==root and root.stat().st_uid==1000 and stat.S_IMODE(root.stat().st_mode)==0o700
names=('host-sources/retirement_host.py','backend-sources/retirement/checkpoint.py','backend-sources/retirement/fingerprints.py','backend-sources/retirement/interlock.py','backend-sources/retirement/publisher.py')
def read(name,limit):
 path=root/name;assert path.resolve()==path
 fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC)
 try:
  before=os.fstat(fd);assert stat.S_ISREG(before.st_mode) and before.st_uid==1000 and before.st_nlink==1 and stat.S_IMODE(before.st_mode)==0o600 and 0<before.st_size<=limit
  with os.fdopen(fd,'rb',closefd=False) as stream:body=stream.read(limit+1)
  after=os.fstat(fd);named=path.lstat();assert len(body)==before.st_size and (after.st_dev,after.st_ino,after.st_size)==(before.st_dev,before.st_ino,before.st_size)==(named.st_dev,named.st_ino,named.st_size)
  return body
 finally:os.close(fd)
raw=read('code-manifest.json',16384);assert hashlib.sha256(raw).hexdigest()==sys.argv[1]
manifest=json.loads(raw);assert set(manifest)==set(names)
sources={name:read(name,131072) for name in names};assert all(hashlib.sha256(raw).hexdigest()==manifest[name] for name,raw in sources.items())
# Import ONLY the four already-FD-verified source byte strings. A host source
# replacement after verification cannot substitute code when keys are opened.
package=types.ModuleType('retirement');package.__path__=[];sys.modules['retirement']=package
for leaf in ('fingerprints','checkpoint','interlock','publisher'):
 name='retirement.'+leaf;relative='backend-sources/retirement/'+leaf+'.py';path=str(root/relative)
 module=types.ModuleType(name);module.__file__=path;module.__package__='retirement';sys.modules[name]=module
 exec(compile(sources[relative],path,'exec'),module.__dict__)
entry=str(root/'host-sources/retirement_host.py');deadline=sys.argv[2];sys.argv=[entry,'--execute','--deadline',deadline];exec(compile(sources['host-sources/retirement_host.py'],entry,'exec'),{'__name__':'__main__','__file__':entry})
"""


def launch(root=PRIVATE, expected=REVIEWED_CODE_SHA256, *, image=IMAGE):
    if not re.fullmatch("[a-f0-9]{64}", expected):
        return "disabled"
    if not re.fullmatch("sha256:[a-f0-9]{64}", image):
        raise Unavailable()
    if os.name != "posix" or os.geteuid() != 1000:
        raise Unavailable()
    for path in (root.parent, root, root / "authority", root / "host"):
        directory(path)
    code_ready(root / "code", expected)
    with singleton(root / "host") as acquired:
        if not acquired:
            return "busy"
        append_flag(root / "authority/checkpoints.bin")
        # Metadata only in the host launcher. Key/config content is opened ONLY
        # by verified code in the separate publisher container, never backend.
        for path, limit, exact in (
            (root / "host/host.json", 4096, None),
            (root / "host/signing.key", 32, 32),
        ):
            fd = file_fd(path, limit, exact=exact)
            os.close(fd)
        binary, endpoint = (
            Path("/usr/bin/docker").stat(),
            Path("/var/run/docker.sock").lstat(),
        )
        if (
            not stat.S_ISREG(binary.st_mode)
            or binary.st_uid != 0
            or binary.st_mode & 0o022
            or not stat.S_ISSOCK(endpoint.st_mode)
            or endpoint.st_uid != 0
        ):
            raise Unavailable()
        docker = Docker()
        if docker.ids("label=io.aqua.purpose=" + PURPOSE) or docker.ids(
            "name=^/" + NAME + "$"
        ):
            raise Unavailable()
        if docker.call("image", "inspect", "--format", "{{.Id}}", image) != image:
            raise Unavailable()
        if (
            docker.call("volume", "inspect", "--format", "{{.Name}}", SOCKET_VOLUME)
            != SOCKET_VOLUME
        ):
            raise Unavailable()
        nonce, identifier = secrets.token_hex(16), None
        try:
            identifier = docker.call(
                "container",
                "create",
                "--pull=never",
                "--name",
                NAME,
                "--label",
                "io.aqua.purpose=" + PURPOSE,
                "--label",
                "io.aqua.run=" + nonce,
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges:true",
                "--memory=128m",
                "--memory-swap=128m",
                "--cpus=1",
                "--pids-limit=32",
                "--user=1000:1000",
                "--restart=no",
                "--log-driver=none",
                "--no-healthcheck",
                "--stop-timeout=1",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=8388608",
                "--mount",
                "type=bind,src="
                + str(root / "authority")
                + ",dst=/run/aqua-retirement",
                "--mount",
                "type=bind,src="
                + str(root / "host")
                + ",dst=/run/aqua-retirement-host,readonly",
                "--mount",
                "type=bind,src=" + str(root / "code") + ",dst=/publisher,readonly",
                "--mount",
                "type=volume,src=" + SOCKET_VOLUME + ",dst=/run/aqua-app-db,readonly",
                "--env=PYTHON_DOTENV_DISABLED=1",
                "--env=PYTHONDONTWRITEBYTECODE=1",
                "--entrypoint=python",
                image,
                "-E",
                "-s",
                "-B",
                "-c",
                VERIFY_CODE,
                expected,
                str(docker.work_deadline - 2),
            )
            if not IDENT.fullmatch(identifier):
                identifier = None
                raise Unavailable()
            if docker.owned(nonce) != identifier:
                raise Unavailable()
            result = json.loads(
                docker.call("container", "start", "--attach", identifier, timeout=50)
            )
            if (
                type(result) is not dict
                or set(result) != {"status", "steps"}
                or result["status"] not in {"idle", "checked"}
                or type(result["steps"]) is not int
                or not 0 <= result["steps"] <= 55
            ):
                raise Unavailable()
            return result["status"]
        finally:
            if not docker.clean(nonce, identifier):
                raise Unavailable()


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "production_enabled": False,
                    "secret_reads": 0,
                    "Docker_actions": 0,
                }
            )
        )
    elif sys.argv[1:] == ["--execute"]:

        def interrupted(*args):
            raise Unavailable()

        signal.signal(signal.SIGTERM, interrupted)
        signal.signal(signal.SIGINT, interrupted)
        try:
            status = launch()
        except BaseException:
            print(json.dumps({"status": "unavailable"}))
            raise SystemExit(1) from None
        print(json.dumps({"status": status}))
    else:
        raise SystemExit(2)
