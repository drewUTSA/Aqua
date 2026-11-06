"""Prepare public source; opt in to a closed isolated guard suite."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import signal
import subprocess
import tarfile
import time

from run_backend import ROOT, source_archive

PURPOSE = "retirement-native-protocol"
DOCKER = ["/usr/bin/docker", "--host=unix:///var/run/docker.sock"]
ENV = {
    "PATH": "/usr/bin:/bin",
    "HOME": "/proc/self/fd",
    "DOCKER_CONFIG": "/proc/self/fd",
}
MAX_SOURCE, MAX_LOG = 16 * 1024**2, 65536
EXEC_SECONDS = 60
COUNTS = {"status": "passed", "tests": 80, "failures": 0, "errors": 0, "skipped": 0}
SUITES = {
    "protocol80": (80, "/checks/tools/checks/run_retirement_protocol.py"),
    "archival9": (9, "/checks/tools/checks/run_retirement_archival.py"),
    "operator77": (77, "/checks/tools/checks/run_retirement_operator.py"),
    "fixtures36": (36, "/checks/tools/checks/run_retirement_fixture_guards.py"),
    "backups56": (56, "/checks/tools/checks/run_retirement_backup_models.py"),
    "signals48": (48, "/checks/tools/checks/run_retirement_signals.py"),
}
HBA = "ops/appdb/pg_hba.conf"
CLIENT_MANIFEST = "ops/retirement/backup_client/vendor-manifest.json"
BOOTSTRAP = """
import io,os,pathlib,sys,tarfile
data=sys.stdin.buffer.read(16777217)
if not 0<len(data)<=16777216: raise RuntimeError('native_source_bound')
with tarfile.open(fileobj=io.BytesIO(data)) as archive:
 members=archive.getmembers()
 if len(members)>4096 or sum(m.size for m in members)>16777216: raise RuntimeError('native_source_bound')
 for m in members:
  p=pathlib.PurePosixPath(m.name)
  asset=p.parent==pathlib.PurePosixPath('backend/auth') and p.name in {'password_blocklist_sha256.txt','password_blocklist_LICENSE.txt','password_blocklist_provenance.json'}
  hba=p.as_posix()=='ops/appdb/pg_hba.conf' and sys.argv[1]=='/checks/tools/checks/run_retirement_operator.py'
  client=p.as_posix()=='ops/retirement/backup_client/vendor-manifest.json' and sys.argv[1]=='/checks/tools/checks/run_retirement_backup_models.py'
  if not m.isfile() or p.is_absolute() or not p.parts or '..' in p.parts or any(x.startswith('.') for x in p.parts) or p.parts[0] not in {'backend','eval','ops','tools'} or (p.parts[0]=='tools' and p.parts[:2]!=('tools','checks')) or (not asset and not hba and not client and p.suffix not in {'.py','.sql','.psql','.ini'}) or not 0<=m.size<=4194304 or ((hba or client) and not 0<m.size<=131072): raise RuntimeError('native_source_member_denied')
 archive.extractall('/checks',filter='data')
os.chdir('/checks/backend')
os.execv(sys.executable,[sys.executable,'-B',sys.argv[1]])
"""


def image_id(value: str) -> str:
    if type(value) is not str or not re.fullmatch(r"sha256:[a-f0-9]{64}", value):
        raise argparse.ArgumentTypeError("immutable_image_required")
    return value


def suite_spec(suite: str) -> tuple[int, str]:
    if type(suite) is not str or suite not in SUITES:
        raise ValueError("native_suite_invalid")
    return SUITES[suite]


def prepared(data: bytes, suite: str = "protocol80") -> dict:
    expected_tests, _ = suite_spec(suite)
    if not 0 < len(data) <= MAX_SOURCE:
        raise ValueError("native_source_bound")
    with tarfile.open(fileobj=io.BytesIO(data)) as archive:
        members = archive.getmembers()
        names = set()
        for member in members:
            path = Path(member.name)
            asset = path.parent.as_posix() == "backend/auth" and path.name in {
                "password_blocklist_sha256.txt",
                "password_blocklist_LICENSE.txt",
                "password_blocklist_provenance.json",
            }
            hba = suite == "operator77" and member.name == HBA
            client = suite == "backups56" and member.name == CLIENT_MANIFEST
            if (
                not member.isfile()
                or path.is_absolute()
                or not path.parts
                or ".." in path.parts
                or any(part.startswith(".") for part in path.parts)
                or path.parts[0] not in {"backend", "eval", "ops", "tools"}
                or path.parts[0] == "tools"
                and path.parts[:2] != ("tools", "checks")
                or not asset
                and not hba
                and not client
                and path.suffix not in {".py", ".sql", ".psql", ".ini"}
                or member.name in names
                or not 0 <= member.size <= 4194304
                or (hba or client)
                and not 0 < member.size <= 131072
            ):
                raise ValueError("native_source_member_denied")
            names.add(member.name)
        if len(members) > 4096 or sum(member.size for member in members) > MAX_SOURCE:
            raise ValueError("native_source_member_denied")
        if suite == "operator77" and HBA not in names:
            raise ValueError("native_operator_public_HBA_required")
        if suite == "backups56" and CLIENT_MANIFEST not in names:
            raise ValueError("native_backup_public_manifest_required")
    return {
        "status": "prepared",
        "source_bytes": len(data),
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "expected_tests": expected_tests,
        "suite": suite,
        "limits": {
            "memory_bytes": 134217728,
            "cpus": 1,
            "checks_tmpfs_bytes": 67108864,
            "execution_seconds": EXEC_SECONDS,
            "log_bytes": MAX_LOG,
        },
        "network": "none",
        "uid": 1000,
        "postgres": False,
        "host_mounts": False,
    }


def suite_source(suite: str) -> bytes:
    """Add only each closed suite's exact bounded public metadata input."""
    suite_spec(suite)
    data = source_archive()
    extra = {"operator77": HBA, "backups56": CLIENT_MANIFEST}.get(suite)
    if extra is None:
        return data
    prepared(data)
    path = ROOT / extra
    if path.is_symlink() or path.resolve(strict=True) != path or not path.is_file():
        raise ValueError("native_operator_public_HBA_not_regular")
    raw = path.read_bytes()
    if not 0 < len(raw) <= 131072:
        raise ValueError("native_operator_public_HBA_bound")
    output = io.BytesIO()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as original:
        with tarfile.open(fileobj=output, mode="w") as archive:
            for member in original:
                source = original.extractfile(member)
                if source is None:
                    raise ValueError("native_source_member_denied")
                archive.addfile(member, source)
            info = tarfile.TarInfo(extra)
            info.size, info.mode, info.uid, info.gid = len(raw), 0o644, 1000, 1000
            archive.addfile(info, io.BytesIO(raw))
    value = output.getvalue()
    prepared(value, suite)
    return value


def command(*args: str) -> bytes:
    result = subprocess.run(
        DOCKER + list(args), capture_output=True, timeout=10, env=ENV
    )
    if result.returncode or len(result.stdout) > 4096:
        raise RuntimeError("native_docker_command_failed")
    return result.stdout


def owned(name: str, reference: str) -> str | None:
    if not re.fullmatch(r"aqua-native-protocol-[a-f0-9]{24}", name) or not (
        reference == name or re.fullmatch(r"[a-f0-9]{64}", reference)
    ):
        raise ValueError("native_resource_scope_invalid")
    template = '{{json .Id}}\n{{json .Name}}\n{{json (index .Config.Labels "io.aqua.purpose")}}\n{{json (index .Config.Labels "io.aqua.run")}}'
    result = subprocess.run(
        DOCKER + ["container", "inspect", reference, "--format", template],
        capture_output=True,
        timeout=10,
        env=ENV,
    )
    absent = (
        rb"(?:error(?: response from daemon)?:\s*)?no such (?:container|object):\s*"
        + re.escape(reference.encode())
        + rb"\s*"
    )
    if (
        result.returncode == 1
        and result.stdout.strip() in {b"", b"[]"}
        and re.fullmatch(absent, result.stderr.strip().lower())
    ):
        return None
    if result.returncode or len(result.stdout) > 4096:
        raise RuntimeError("native_resource_inspect_failed")
    values = result.stdout.splitlines()
    if len(values) != 4:
        raise RuntimeError("native_resource_metadata_invalid")
    ident, observed, purpose, run = (json.loads(value) for value in values)
    if (
        not isinstance(ident, str)
        or not re.fullmatch(r"[a-f0-9]{64}", ident)
        or observed != "/" + name
        or purpose != PURPOSE
        or run != name
        or reference != name
        and ident != reference
    ):
        raise RuntimeError("native_resource_ownership_mismatch")
    return ident


def cleanup(name: str, expected: str | None) -> bool:
    try:
        ident = owned(name, name)
        if ident is None:
            return expected is not None and owned(name, expected) is None
        if expected is not None and ident != expected:
            return False
        try:
            command("container", "rm", "--force", ident)
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            pass
        return owned(name, name) is None and owned(name, ident) is None
    except (RuntimeError, ValueError, OSError, subprocess.TimeoutExpired):
        return False


def stream(ident: str, data: bytes, log: Path) -> tuple[int, bytes]:
    """Bound stdin, live combined output and the attached CLI lifetime."""
    process = subprocess.Popen(
        DOCKER + ["start", "--attach", "--interactive", ident],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=ENV,
    )
    output = bytearray()
    try:
        assert process.stdin is not None and process.stdout is not None
        for pipe in (process.stdin, process.stdout):
            os.set_blocking(pipe.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdin, selectors.EVENT_WRITE)
            selector.register(process.stdout, selectors.EVENT_READ)
            offset, until = 0, time.monotonic() + EXEC_SECONDS
            while selector.get_map():
                if time.monotonic() >= until:
                    raise TimeoutError("native_execution_deadline")
                for key, _ in selector.select(
                    max(0, min(0.2, until - time.monotonic()))
                ):
                    if key.fileobj is process.stdin:
                        try:
                            offset += os.write(key.fd, data[offset : offset + 32768])
                        except BlockingIOError:
                            continue
                        if offset == len(data):
                            selector.unregister(process.stdin)
                            process.stdin.close()
                    else:
                        try:
                            chunk = os.read(key.fd, 32768)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(process.stdout)
                        elif len(output) + len(chunk) > MAX_LOG:
                            raise RuntimeError("native_log_bound")
                        else:
                            output.extend(chunk)
            return process.wait(timeout=max(0.01, until - time.monotonic())), bytes(
                output
            )
    finally:
        try:
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
        finally:
            for pipe in (process.stdin, process.stdout):
                if pipe is not None:
                    pipe.close()
            log.write_bytes(output)


def result_counts(log: bytes, suite: str = "protocol80") -> dict:
    expected = {**COUNTS, "tests": suite_spec(suite)[0]}

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("native_result_duplicate")
            result[key] = value
        return result

    lines = log.splitlines()
    if not lines or len(lines[-1]) > 4096:
        raise ValueError("native_result_invalid")
    counts = json.loads(lines[-1], object_pairs_hook=unique)
    if (
        counts != expected
        or set(counts) != set(expected)
        or any(
            type(counts[key]) is not int
            for key in ("tests", "failures", "errors", "skipped")
        )
    ):
        raise ValueError(
            "native_exact48_not_passed"
            if suite == "signals48"
            else (
                "native_exact80_not_passed"
                if suite == "protocol80"
                else (
                    "native_exact9_not_passed"
                    if suite == "archival9"
                    else (
                        "native_exact77_not_passed"
                        if suite == "operator77"
                        else (
                            "native_exact36_not_passed"
                            if suite == "fixtures36"
                            else "native_exact56_not_passed"
                        )
                    )
                )
            )
        )
    return counts


def execute(
    image: str,
    output: Path,
    data: bytes,
    *,
    signals: dict[str, bool] | None = None,
    suite: str = "protocol80",
) -> dict:
    report = {
        **prepared(data, suite),
        "status": "failed",
        "image": image_id(image),
        "cleanup": "not_started",
    }
    if output.is_symlink():
        raise ValueError("native_output_symlink_denied")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    name = "aqua-native-protocol-" + secrets.token_hex(12)
    report["run"] = name
    started, expected = False, None
    try:
        if (
            command("image", "inspect", image, "--format", "{{.Id}}").decode().strip()
            != image
            or owned(name, name) is not None
        ):
            raise RuntimeError("native_preflight_invalid")
        started = True
        raw = (
            command(
                "create",
                "--name",
                name,
                "--label=io.aqua.purpose=" + PURPOSE,
                "--label=io.aqua.run=" + name,
                "--pull=never",
                "--network=none",
                "--read-only",
                "--interactive",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--memory=128m",
                "--memory-swap=128m",
                "--cpus=1",
                "--pids-limit=64",
                "--user=1000:1000",
                "--tmpfs=/checks:rw,nosuid,nodev,size=67108864,uid=1000,gid=1000,mode=0700",
                "--tmpfs=/tmp:rw,nosuid,nodev,noexec,size=8388608,uid=1000,gid=1000,mode=0700",
                "--env=PYTHONPATH=/checks/backend:/checks/tools/checks/retirement_fixture",
                "--env=PYTHONDONTWRITEBYTECODE=1",
                "--env=PYTHON_DOTENV_DISABLED=1",
                "--workdir=/checks",
                "--entrypoint=python",
                image,
                "-B",
                "-c",
                BOOTSTRAP,
                suite_spec(suite)[1],
            )
            .decode()
            .strip()
        )
        if not re.fullmatch(r"[a-f0-9]{64}", raw) or owned(name, name) != raw:
            raise RuntimeError("native_create_unconfirmed")
        expected = raw
        code, log = stream(expected, data, output / "native.log")
        (output / "native.log").write_bytes(log)
        report["log_sha256"] = hashlib.sha256(log).hexdigest()
        report["counts"] = result_counts(log, suite)
        if code != 0:
            raise RuntimeError("native_process_failed")
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        report["error_category"] = type(error).__name__
    finally:
        if signals is not None:
            signals["cleaning"] = True
        removed = not started or cleanup(name, expected)
        report["cleanup"] = (
            ("removed_and_absence_confirmed" if removed else "unconfirmed")
            if started
            else "not_created"
        )
        log = output / "native.log"
        if log.is_file():
            report["log_sha256"] = hashlib.sha256(log.read_bytes()).hexdigest()
        if not removed:
            report["status"] = "failed"
        if signals is not None and signals["cancelled"]:
            report["status"], report["error_category"] = "failed", "Interrupted"
        (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--suite", choices=tuple(SUITES), default="protocol80")
    parser.add_argument("--image", type=image_id)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if (
        args.execute != (args.image is not None and args.output is not None)
        or not args.execute
        and (args.image is not None or args.output is not None)
    ):
        parser.error("execute_requires_immutable_image_and_fresh_output")
    data = suite_source(args.suite)
    if not args.execute:
        print(json.dumps(prepared(data, args.suite)))
        return 0

    signals = {"cleaning": False, "cancelled": False}

    def stop(signum: int, frame: object) -> None:
        if not signals["cancelled"]:
            signals["cancelled"] = True
            if not signals["cleaning"]:
                raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    report = execute(args.image, args.output, data, signals=signals, suite=args.suite)
    print(json.dumps(report))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
