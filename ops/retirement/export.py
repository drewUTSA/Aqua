"""Stopped-writer authority head/export; binary output goes only to encryption.

Default does nothing. Explicit actions require the pinned installation profile,
actual live maintenance holder and verified private code/image before key mounts.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import re
import signal
import sys

if __package__:
    from . import maintenance
    from .operator_scope import PRODUCTION, Scope
    from .export_code import verify
    from .export_protocol import Channel, MAX_DUMP, archive
    from .export_resources import Owned
    from .operator_files import PRIVATE, read, pinned
else:
    import maintenance
    from operator_scope import PRODUCTION, Scope
    from export_code import verify
    from export_protocol import Channel, MAX_DUMP, archive
    from export_resources import Owned
    from operator_files import PRIVATE, read, pinned

PUBLIC = {
    "schemaVersion",
    "installation_id",
    "identity_key_id",
    "key_commitment",
    "public_key",
    "runtime_image",
    "source_sha256",
}
FIELDS = PUBLIC | {
    "plan_sha256",
    "verification_sha256",
    "code_manifest_sha256",
    "host_code_manifest_sha256",
}


class Cancelled(RuntimeError):
    pass


def profile(expected: str, scope=PRODUCTION) -> dict:
    root = PRIVATE if scope is PRODUCTION else scope.private
    if not re.fullmatch(r"[a-f0-9]{64}", expected):
        raise RuntimeError("retirement_export_expected_profile_required")
    value = pinned(root / "operator/installation.json", expected)
    if (
        set(value) != FIELDS
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
    ):
        raise RuntimeError("retirement_export_installation_profile_invalid")
    from uuid import UUID

    for name in ("installation_id", "identity_key_id"):
        if type(value[name]) is not str or str(UUID(value[name])) != value[name]:
            raise RuntimeError("retirement_export_installation_profile_invalid")
    for name in FIELDS - {"schemaVersion", "installation_id", "identity_key_id"}:
        pattern = r"sha256:[a-f0-9]{64}" if name == "runtime_image" else r"[a-f0-9]{64}"
        if type(value[name]) is not str or not re.fullmatch(pattern, value[name]):
            raise RuntimeError("retirement_export_installation_profile_invalid")
    return value


def boundary(value: dict, scope=PRODUCTION):
    plan, state, digest = maintenance.require(value["plan_sha256"], 9, scope=scope)
    if (plan["runtime_image"], plan["source_sha256"]) != (
        value["runtime_image"],
        value["source_sha256"],
    ):
        raise RuntimeError("retirement_export_runtime_source_changed")
    return state, digest


def dump(owner) -> bytes:
    password = read(owner.private / "operator/backup.password", 43)
    if not re.fullmatch(rb"[A-Za-z0-9_-]{43}", password):
        raise RuntimeError("retirement_export_backup_credential_invalid")
    process = owner.start("dump")
    channel = Channel(process, owner.until)
    channel.write(password + b"\n")
    process.stdin.close()
    raw = bytearray()
    while True:
        chunk = channel.receive()
        if not chunk:
            break
        raw.extend(chunk)
        if len(raw) > MAX_DUMP:
            raise RuntimeError("retirement_export_dump_capacity")
    if process.wait(timeout=max(0.01, channel.remaining())) != 0 or not raw.startswith(
        b"PGDMP"
    ):
        raise RuntimeError("retirement_export_dump_failed")
    if not owner.remove("dump"):
        raise RuntimeError("retirement_export_dump_exit_unconfirmed")
    return bytes(raw)


def execute(action: str, expected: str, sink=None, scope=PRODUCTION) -> dict | None:
    scope.validate()
    root = PRIVATE if scope is PRODUCTION else scope.private
    if action not in {"head", "export"}:
        raise ValueError("retirement_export_action_invalid")
    if action == "export" and (sink is None and sys.stdout.isatty()):
        raise RuntimeError("retirement_export_requires_encryption_pipe")
    previous = {}
    cleaning = False
    owner = None

    def cancel(number, frame):
        if not cleaning:
            raise Cancelled("retirement_export_cancelled")

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGALRM):
        previous[number] = signal.getsignal(number)
        signal.signal(number, cancel)
    signal.alarm(120)
    try:
        value = profile(expected, scope)
        if __package__:
            from .install import sources
        else:
            from install import sources
        sources(value["host_code_manifest_sha256"])
        before, digest = boundary(value, scope)
        code = root / "operator/code"
        verify(code, value["code_manifest_sha256"])
        for directory in ("public", "export") if action == "export" else ("public",):
            raw = read(root / "operator" / directory / "verification.json", 4096)
            if hashlib.sha256(raw).hexdigest() != value[
                "verification_sha256"
            ] or json.loads(raw) != {name: value[name] for name in PUBLIC}:
                raise RuntimeError("retirement_export_public_profile_changed")
        owner = Owned(value, scope=scope)
        if (
            owner.command(
                "image", "inspect", value["runtime_image"], "--format={{.Id}}"
            ).strip()
            != value["runtime_image"].encode()
        ):
            raise RuntimeError("retirement_export_runtime_image_changed")
        process = owner.start("peer", action)
        channel = Channel(process, owner.until)
        if action == "export":
            archive(channel, lambda: dump(owner), sink or sys.stdout.buffer)
            result = None
        else:
            output = bytearray()
            while True:
                chunk = channel.receive()
                if not chunk:
                    break
                output.extend(chunk)
                if len(output) > 16384:
                    raise RuntimeError("retirement_export_head_capacity")
            if process.wait(timeout=max(0.01, channel.remaining())) != 0:
                raise RuntimeError("retirement_export_head_failed")
            result = json.loads(output)
            if (
                any(result.get(name) != value[name] for name in PUBLIC)
                or result.get("total_host_restore_supported") is not False
            ):
                raise RuntimeError("retirement_export_head_profile_mismatch")
        cleaning = True
        signal.alarm(0)
        owner.close()
        owner = None
        after, again = boundary(value, scope)
        if after != before or again != digest:
            raise RuntimeError("retirement_export_maintenance_changed")
        if result is not None:
            result.update(
                mode="retained_authority_stopped_writers",
                profile_sha256=expected,
                maintenance_nonce=before["nonce"],
                maintenance_expires_utc=before["expires_utc"],
                checked_utc=datetime.now(timezone.utc).isoformat(),
                maintenance_receipt_sha256=digest,
                holders_stopped={
                    name: "absence_confirmed"
                    for name in (
                        "web",
                        "analysis",
                        "export",
                        "download",
                        "deletion",
                        "mail",
                        "publisher",
                    )
                },
            )
        return result
    finally:
        cleaning = True
        signal.alarm(0)
        try:
            if owner is not None:
                owner.close()
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=("head", "export"))
    parser.add_argument("--profile-sha256", default="")
    parser.add_argument("--qa-run")
    args = parser.parse_args()
    if args.action is None:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "private_reads": 0,
                    "writes": 0,
                    "Docker_actions": 0,
                    "total_host_restore_supported": False,
                }
            )
        )
        return
    result = execute(
        args.action,
        args.profile_sha256,
        scope=Scope(args.qa_run) if args.qa_run is not None else PRODUCTION,
    )
    if result is not None:
        print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
