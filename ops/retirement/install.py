"""Create-only retained authority installation while actual writers stay stopped.

No default execution or automatic application/cron resume. Partial installation
is preserved, including APPEND, and must stay maintenance until reviewed repair.
"""

import argparse
from contextlib import ExitStack
import math
import time
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import stat
import subprocess
import sys

if __package__:
    from . import maintenance
    from .operator_scope import PRODUCTION, Scope
    from .export_code import FILES as EXPORT_FILES
    from .install_resources import Installer, ack_program
    from .operator_files import PRIVATE, directory, json_bytes, parse, read, write_once
    from .publisher_launcher import FILES as PUBLISHER_FILES
else:
    import maintenance
    from operator_scope import PRODUCTION, Scope
    from export_code import FILES as EXPORT_FILES
    from install_resources import Installer, ack_program
    from operator_files import PRIVATE, directory, json_bytes, parse, read, write_once
    from publisher_launcher import FILES as PUBLISHER_FILES

STAGE = Path(__file__).resolve().parent
PROFILE = PRIVATE.parent / "retirement-install.json"
SOURCE_NAMES = frozenset(
    {
        "materialize.py",
        "initialize.py",
        "append_provision.py",
        "retirement_host.py",
        "bootstrap.psql",
        "schema.psql",
        "backup.psql",
        *EXPORT_FILES,
        # The parent reviews the complete controller closure, including its launch
        # and cancellation/ownership boundaries, not just the inner container code.
        "install.py",
        "install_resources.py",
        "operator_files.py",
        "operator_scope.py",
        "maintenance.py",
        "export.py",
        "export_code.py",
        "export_resources.py",
        "export_protocol.py",
        "publisher_launcher.py",
        "installed_publisher.py",
        "recover.py",
        "recovery_driver.py",
        "restore_session_fence.sql",
        "backend-sources/retirement/checkpoint.py",
        "backend-sources/retirement/fingerprints.py",
        "backend-sources/retirement/interlock.py",
        "backend-sources/retirement/publisher.py",
    }
)
FIELDS = {
    "schemaVersion",
    "runtime_image",
    "source_sha256",
    "plan_sha256",
    "code_manifest_sha256",
}


def profile(expected: str, scope=PRODUCTION) -> dict:
    raw = read(PROFILE if scope is PRODUCTION else scope.install_profile)
    if (
        not re.fullmatch(r"[a-f0-9]{64}", expected)
        or hashlib.sha256(raw).hexdigest() != expected
    ):
        raise RuntimeError("retirement_install_profile_pin_invalid")
    value = parse(raw)
    if (
        set(value) != FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
    ):
        raise RuntimeError("retirement_install_profile_invalid")
    for name in FIELDS - {"schemaVersion"}:
        pattern = r"sha256:[a-f0-9]{64}" if name == "runtime_image" else r"[a-f0-9]{64}"
        if type(value[name]) is not str or not re.fullmatch(pattern, value[name]):
            raise RuntimeError("retirement_install_profile_invalid")
    return value


def sources(expected: str) -> dict[str, bytes]:
    raw = read(STAGE / "installation-sources.json", 16384)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise RuntimeError("retirement_install_source_manifest_invalid")
    manifest = parse(raw)
    if set(manifest) != SOURCE_NAMES:
        raise RuntimeError("retirement_install_source_set_invalid")
    cache = {name: read(STAGE / name, 131072) for name in SOURCE_NAMES}
    if any(
        hashlib.sha256(raw).hexdigest() != manifest[name] for name, raw in cache.items()
    ):
        raise RuntimeError("retirement_install_source_bytes_changed")
    return cache


def sql(database: str, raw: bytes) -> bytes:
    if not re.fullmatch(r"[a-f0-9]{64}", database) or len(raw) > 262144:
        raise RuntimeError("retirement_install_SQL_scope_invalid")
    result = subprocess.run(
        [
            *maintenance.DOCKER,
            "exec",
            "-i",
            database,
            "psql",
            "-X",
            "-v",
            "ON_ERROR_STOP=1",
            "-U",
            "postgres",
            "-d",
            "postgres",
            "-At",
        ],
        input=raw,
        capture_output=True,
        timeout=30,
        env=maintenance.ENV,
        close_fds=True,
    )
    if result.returncode or len(result.stdout) > 16384:
        # SQL can mention secret literals in error context: never emit stderr.
        raise RuntimeError("retirement_install_SQL_failed")
    return result.stdout


def provision_database(value: dict, public: dict, cache: dict, root=PRIVATE) -> None:
    prefix = b""
    for role in ("writer", "recovery", "checkpoint", "backup"):
        password = read(root / "operator" / f"{role}.password", 43)
        if not re.fullmatch(rb"[A-Za-z0-9_-]{43}", password):
            raise RuntimeError("retirement_install_generated_credential_invalid")
        prefix += b"\\set " + role.encode() + b"_password '" + password + b"'\n"
    for name in ("installation_id", "identity_key_id", "key_commitment"):
        # Already strict typed public output from materialize, revalidated by
        # install before SQL substitution. No arbitrary value enters psql syntax.
        prefix += ("\\set " + name + " '" + public[name] + "'\n").encode()
    sql(
        value["database_id"],
        prefix
        + cache["bootstrap.psql"]
        + b"\n"
        + cache["schema.psql"]
        + b"\n"
        + cache["backup.psql"],
    )


def sync_directory(path: Path) -> None:
    """Persist new child entries through the verified parent directory inode."""
    directory(path)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened, named = os.fstat(fd), path.lstat()
        if (
            not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != 1000
            or stat.S_IMODE(opened.st_mode) != 0o700
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
            or path.resolve(strict=True) != path
        ):
            raise RuntimeError("retirement_install_directory_changed")
        os.fsync(fd)
        named = path.lstat()
        if (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino):
            raise RuntimeError("retirement_install_directory_changed")
    finally:
        os.close(fd)


def copy_code(cache: dict, root=PRIVATE) -> tuple[str, str]:
    publisher = {
        "host-sources/retirement_host.py": cache["retirement_host.py"],
        **{
            name: cache[name]
            for name in PUBLISHER_FILES
            if name.startswith("backend-sources/")
        },
    }
    (root / "code").mkdir(mode=0o700)
    os.chmod(root / "code", 0o700)
    for parent in ("host-sources", "backend-sources", "backend-sources/retirement"):
        path = root / "code" / parent
        path.mkdir(mode=0o700)
        os.chmod(path, 0o700)
    for name, raw in publisher.items():
        write_once(root / "code" / name, raw)
    publisher_raw = json_bytes(
        {name: hashlib.sha256(raw).hexdigest() for name, raw in publisher.items()}
    )
    write_once(root / "code/code-manifest.json", publisher_raw)
    exporter = {name: cache[name] for name in EXPORT_FILES}
    for name, raw in exporter.items():
        write_once(root / "operator/code" / name, raw)
    exporter_raw = json_bytes(
        {name: hashlib.sha256(raw).hexdigest() for name, raw in exporter.items()}
    )
    write_once(root / "operator/code/code-manifest.json", exporter_raw)
    # Persist every new code-directory entry before initializer admission.
    for parent in (root / "code/backend-sources", root / "code", root):
        sync_directory(parent)
    return (
        hashlib.sha256(publisher_raw).hexdigest(),
        hashlib.sha256(exporter_raw).hexdigest(),
    )


def execute(expected: str, *, retain=None, scope=PRODUCTION) -> dict:
    scope.validate()
    root = PRIVATE if scope is PRODUCTION else scope.private
    prior = {}
    cleaning = False
    owner = None

    def cleanup_owner():
        nonlocal owner, cleaning
        cleaning = True
        signal.alarm(0)
        current, owner = owner, None
        if current is not None:
            current.close()

    def cancel(number, frame):
        if not cleaning:
            raise RuntimeError("retirement_install_cancelled")

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
        prior[number] = signal.getsignal(number)
        signal.signal(number, cancel)
    signal.alarm(180)
    try:
        spec = profile(expected, scope)
        cache = sources(spec["code_manifest_sha256"])
        with (
            maintenance.Hold(spec["plan_sha256"], scope=scope) as held,
            ExitStack() as resources,
        ):
            if (held.value["runtime_image"], held.value["source_sha256"]) != (
                spec["runtime_image"],
                spec["source_sha256"],
            ):
                raise RuntimeError("retirement_install_runtime_source_mismatch")
            held.require(9)
            # Do not generate a key or create a private root if independent
            # roles/database already exist. No destructive/reuse installation.
            if (
                sql(
                    held.value["database_id"],
                    b"SELECT EXISTS(SELECT 1 FROM pg_database WHERE datname='aqua_retirement') OR EXISTS(SELECT 1 FROM pg_roles WHERE rolname LIKE 'aqua_retirement_%');",
                ).strip()
                != b"f"
            ):
                raise RuntimeError("retirement_install_existing_authority")
            directory(root.parent)
            root.mkdir(mode=0o700)  # existing root fails; never delete/retry it
            os.chmod(root, 0o700)
            # Persist this scoped root before generating keys or committing SQL.
            sync_directory(root.parent)
            programs = {
                "materialize": cache["materialize.py"],
                "initializer": cache["initialize.py"],
                "setter": cache["append_provision.py"],
                "genesis_ack": ack_program(cache["retirement_host.py"]),
            }
            owner = Installer(spec, programs, scope=scope)
            resources.callback(cleanup_owner)
            if (
                owner.command(
                    "image", "inspect", spec["runtime_image"], "--format={{.Id}}"
                ).strip()
                != spec["runtime_image"].encode()
            ):
                raise RuntimeError("retirement_install_image_mismatch")
            public = owner.once("materialize")
            # Reuse exact strict validation rather than accept issuer-shaped data.
            from uuid import UUID

            if (
                set(public)
                != {
                    "schemaVersion",
                    "installation_id",
                    "identity_key_id",
                    "key_commitment",
                    "public_key",
                    "runtime_image",
                    "source_sha256",
                }
                or type(public["schemaVersion"]) is not int
                or public["schemaVersion"] != 1
            ):
                raise RuntimeError("retirement_install_public_result_invalid")
            for name in ("installation_id", "identity_key_id"):
                if (
                    type(public[name]) is not str
                    or str(UUID(public[name])) != public[name]
                ):
                    raise RuntimeError("retirement_install_public_result_invalid")
            for name in ("key_commitment", "public_key"):
                if type(public[name]) is not str or not re.fullmatch(
                    r"[a-f0-9]{64}", public[name]
                ):
                    raise RuntimeError("retirement_install_public_result_invalid")
            if (public["runtime_image"], public["source_sha256"]) != (
                spec["runtime_image"],
                spec["source_sha256"],
            ):
                raise RuntimeError("retirement_install_public_result_invalid")
            held.publisher()  # keeper takes actual singleton before any signer
            provision_database(held.value, public, cache, root=root)
            publisher_pin, export_pin = copy_code(cache, root=root)
            owner.once("initializer")
            owner.once("setter")
            owner.once("genesis_ack")
            verification = read(root / "operator/public/verification.json", 4096)
            export_profile = {
                **public,
                "plan_sha256": spec["plan_sha256"],
                "verification_sha256": hashlib.sha256(verification).hexdigest(),
                "code_manifest_sha256": export_pin,
                "host_code_manifest_sha256": spec["code_manifest_sha256"],
            }
            write_once(root / "operator/installation.json", json_bytes(export_profile))
            publisher_profile = {
                "schemaVersion": 1,
                "runtime_image": spec["runtime_image"],
                "source_sha256": spec["source_sha256"],
                "code_manifest_sha256": publisher_pin,
                "host_code_manifest_sha256": spec["code_manifest_sha256"],
            }
            write_once(root / "host/publisher.json", json_bytes(publisher_profile))
            cleanup_owner()
            held.require(9)
            receipt = {
                "status": "installed_writers_still_stopped",
                "installation_id": public["installation_id"],
                "export_profile_sha256": hashlib.sha256(
                    json_bytes(export_profile)
                ).hexdigest(),
                "publisher_profile_sha256": hashlib.sha256(
                    json_bytes(publisher_profile)
                ).hexdigest(),
                "initial_encrypted_retention_proven": False,
                "schema9_fallback_proven": False,
                "writers_resumed": False,
                "cron_resumed": False,
                "total_host_restore_supported": False,
            }
            if retain is not None:
                cleaning = False
                signal.alarm(max(1, math.ceil(held.until - time.monotonic())))
                retain(receipt)
                held.require(9)
            return receipt
    finally:
        cleaning = True
        signal.alarm(0)
        for number, handler in prior.items():
            signal.signal(number, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile-sha256", default="")
    parser.add_argument("--qa-run")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "keys_created": 0,
                    "writes": 0,
                    "Docker_actions": 0,
                    "writers_resumed": False,
                }
            )
        )
        return

    def retain(receipt):
        print(json.dumps({**receipt, "maintenance_held": True}), flush=True)
        if sys.stdin.readline().strip() != "release":
            raise RuntimeError("retirement_install_controller_closed")

    print(
        json.dumps(
            execute(
                args.profile_sha256,
                retain=retain,
                scope=Scope(args.qa_run) if args.qa_run is not None else PRODUCTION,
            ),
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
