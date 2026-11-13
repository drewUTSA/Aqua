"""Explicit fresh-QA installer/keeper/head/export/recovery rehearsal; no default actions.

The fixture helper owns PostgreSQL, schema9, the socket and private QA files.
Actual staged CLIs own installation order and all production lock/SQL behavior.
Only allowlisted evidence is printed. Archive/key bytes never enter a file/log.
"""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import re
import select
import signal
import subprocess
import sys
import tarfile
import time

ROOT = Path(__file__).resolve().parents[2]
IMAGE = "sha256:22f90a96931b2be471c31455d97c1da68c3b3c6b6c15ac5fcbfcf362d4b491b0"
RUN = re.compile(r"aqua-retirement-host-[a-f0-9]{24}\Z")
HEX = re.compile(r"[a-f0-9]{64}\Z")
MAX_ARCHIVE = 193 * 1024 * 1024
MAX_DUMP = 128 * 1024 * 1024
ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
PUBLIC = {
    "schemaVersion",
    "installation_id",
    "identity_key_id",
    "key_commitment",
    "public_key",
    "runtime_image",
    "source_sha256",
}


PREFLIGHT_ERRORS = frozenset(
    {
        "operator_stage_full_source_pin_changed",
        "operator_stage_source_member_invalid",
        "operator_stage_source_member_missing",
        "operator_stage_source_member_size",
        "operator_stage_runtime_asset_changed",
        "rehearsal_reviewed_child_lineage_required",
        "rehearsal_exact_strict_HBA_required",
        "rehearsal_exact_app200_manifest_required",
        "rehearsal_runtime_image_changed",
        "rehearsal_postgres_identity",
        "rehearsal_base_not_canonical",
        "rehearsal_source_or_scope_invalid",
        "rehearsal_explicit_native_scope_required",
        "exact_native_QA_scope_required",
        "exact_native_QA_source_root_required",
        "rehearsal_container_command_failed",
    }
)


def public_error(error):
    result = {"error_type": type(error).__name__}
    if (
        type(error) is RuntimeError
        and len(error.args) == 1
        and type(error.args[0]) is str
        and error.args[0] in PREFLIGHT_ERRORS
    ):
        result["error_category"] = error.args[0]
    return result


def require(ok, code):
    if not ok:
        raise RuntimeError(code)


def decoded(raw):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            require(key not in value, "duplicate_public_field")
            value[key] = item
        return value

    value = json.loads(raw, object_pairs_hook=unique)
    require(type(value) is dict, "public_record_not_object")
    return value


def start(stage, run, script, arguments, children):
    require(RUN.fullmatch(run), "explicit_QA_run_required")
    process = subprocess.Popen(
        [
            sys.executable,
            "-E",
            "-s",
            "-B",
            str(stage / script),
            "--qa-run",
            run,
            *arguments,
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        cwd=stage,
        env=ENV,
        bufsize=0,
        close_fds=True,
        start_new_session=True,
    )
    children.append(process)
    return process


def receive(process, limit, until, *, first_line=False):
    """Read the whole bounded output, never a tail-truncating command wrapper."""
    output = io.BytesIO()
    size = 0
    try:
        while True:
            remaining = until - time.monotonic()
            require(remaining > 0, "child_output_deadline")
            ready, _, _ = select.select([process.stdout], [], [], min(0.2, remaining))
            if not ready:
                continue
            raw = os.read(process.stdout.fileno(), min(65536, limit - size + 1))
            if not raw:
                require(not first_line, "keeper_receipt_missing")
                require(
                    process.wait(timeout=max(0.01, remaining)) == 0, "child_exit_failed"
                )
                output.seek(0)
                return output
            # Check before buffering the excess byte. No unbounded communicate().
            require(size + len(raw) <= limit, "child_output_capacity")
            output.write(raw)
            size += len(raw)
            if first_line and b"\n" in raw:
                require(
                    raw.endswith(b"\n") and output.getvalue().count(b"\n") == 1,
                    "keeper_receipt_framing",
                )
                output.seek(0)
                return output
    except BaseException:
        output.close()
        raise


def command(stage, run, action, pin, children, until, limit):
    process = start(
        stage, run, "export.py", ["--action", action, "--profile-sha256", pin], children
    )
    process.stdin.close()
    return receive(process, limit, until)


def checked_head(value, receipt, expected, image):
    require(PUBLIC <= set(value), "head_public_fields_missing")
    require(
        value["schemaVersion"] == 1 and type(value["schemaVersion"]) is int,
        "head_schema_invalid",
    )
    require(
        value["runtime_image"] == image and value["source_sha256"] == expected,
        "head_source_runtime_mismatch",
    )
    require(
        value["installation_id"] == receipt["installation_id"],
        "head_installation_mismatch",
    )
    require(
        type(value.get("sequence")) is int and value["sequence"] == 0,
        "fresh_install_head_not_genesis",
    )
    require(value.get("event_digest") == "0" * 64, "genesis_event_mismatch")
    require(
        value.get("total_host_restore_supported") is False, "unexpected_restore_claim"
    )
    require(
        value.get("mode") == "retained_authority_stopped_writers",
        "head_maintenance_mode",
    )
    require(
        value.get("profile_sha256") == receipt["export_profile_sha256"],
        "head_profile_mismatch",
    )
    require(
        value.get("holders_stopped")
        == {
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
        "head_holders_not_stopped",
    )
    require(
        type(value.get("head_hex")) is str
        and re.fullmatch(r"[a-f0-9]{416}", value["head_hex"]),
        "genesis_record_invalid",
    )
    return value


def checked_archive(stream, head):
    """Stdlib framing/hash check; actual pinned export peer verifies signatures.

    Do not import crypto libraries or inspect keys on the operator host. The
    complete dump is hashed in RAM; pg_dump and peer must already have exited 0.
    """
    view = stream.getbuffer()
    size = len(view)
    digest = hashlib.sha256(view).hexdigest()
    view.release()
    require(0 < size <= MAX_ARCHIVE, "archive_capacity")
    sizes, hashes, checkpoint_tail = {}, {}, b""
    profile = None
    allowed = {
        "profile.json",
        "authority.dump",
        "checkpoints.bin",
        "identity.key",
        "signing.key",
    }
    stream.seek(0)
    with tarfile.open(fileobj=stream, mode="r:") as archive:
        for item in archive:
            cap = (
                65536
                if item.name == "profile.json"
                else (
                    MAX_DUMP
                    if item.name == "authority.dump"
                    else 64 * 1024 * 1024 if item.name == "checkpoints.bin" else 32
                )
            )
            require(
                item.name in allowed
                and item.name not in sizes
                and item.isfile()
                and not item.pax_headers
                and 0 < item.size <= cap
                and item.uid == 1000
                and item.gid == 1000
                and item.mode == 0o600,
                "archive_member_invalid",
            )
            part = archive.extractfile(item)
            require(part is not None, "archive_member_missing")
            with part:
                if item.name == "profile.json":
                    profile = decoded(part.read(65537))
                    sizes[item.name] = item.size
                    continue
                hasher, count, prefix = hashlib.sha256(), 0, b""
                while True:
                    block = part.read(65536)
                    if not block:
                        break
                    if not prefix:
                        prefix = block[:5]
                    count += len(block)
                    require(count <= item.size, "archive_member_overrun")
                    hasher.update(block)
                    if item.name == "checkpoints.bin":
                        checkpoint_tail = (checkpoint_tail + block)[-208:]
                require(count == item.size, "archive_member_truncated")
                if item.name == "authority.dump":
                    require(count > 5 and prefix == b"PGDMP", "dump_format_invalid")
                if item.name in {"identity.key", "signing.key"}:
                    require(count == 32, "archive_key_size")
                sizes[item.name], hashes[item.name] = count, hasher.hexdigest()
        end = archive.offset
    require(set(sizes) == allowed and profile is not None, "archive_incomplete")
    require(
        set(profile) == PUBLIC | {"files"}
        and all(profile[name] == head[name] for name in PUBLIC)
        and profile["files"] == hashes,
        "archive_profile_or_hash_mismatch",
    )
    require(
        sizes["checkpoints.bin"] == 208
        and checkpoint_tail.hex() == head["head_hex"]
        and hashes["checkpoints.bin"] == head["protected_chain_sha256"],
        "archive_genesis_head_mismatch",
    )
    require(1024 <= size - end <= 10240, "archive_tail_length")
    stream.seek(end)
    require(not any(stream.read(10241)), "archive_trailing_payload")
    return {
        "bytes": size,
        "sha256": digest,
        "dump_bytes": sizes["authority.dump"],
        "dump_sha256": hashes["authority.dump"],
        "members": len(sizes),
    }


def checked_recovery(value, head):
    """Genesis-only actual CLI evidence, separate from accepted-data recovery."""
    require(
        value.get("mode") == "retained_authority_app_only"
        and value.get("protected_sha256") == head["protected_chain_sha256"]
        and value.get("ready") is True
        and value.get("pending_manifest") is False
        and type(value.get("events_verified")) is int
        and value["events_verified"] == 0
        and type(value.get("purge_batches")) is int
        and value["purge_batches"] == 0
        and all(
            value.get(name) is False
            for name in (
                "writers_resumed",
                "cron_resumed",
                "total_host_restore_supported",
                "total_host_authority_restore_supported",
            )
        )
        and value.get("physical_mail_validation")
        == "child_owner_mode_readonly_named_inode",
        "genesis_recovery_CLI_not_proven",
    )
    return {
        name: value[name]
        for name in (
            "mode",
            "protected_sha256",
            "ready",
            "pending_manifest",
            "events_verified",
            "purge_batches",
            "physical_mail_validation",
            "writers_resumed",
            "cron_resumed",
            "total_host_restore_supported",
            "total_host_authority_restore_supported",
        )
    }


def stop(process):
    """Require parent exit AND absence of its exact original process group.

    A reaped leader's PID may be reused. Probe that PGID, but never signal it:
    any remaining or ambiguous group keeps private-fixture cleanup blocked.
    """
    stopped = True
    try:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=55)
            except subprocess.TimeoutExpired:
                # Popen targets its own unreaped child. Do not broad-kill Docker
                # or signal a process group after its leader may have exited.
                process.kill()
                process.wait(timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        stopped = False
    finally:
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()
    if not stopped:
        return False
    try:
        os.killpg(process.pid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def execute(root, run, image, expected):
    require(
        sys.platform == "linux"
        and os.geteuid() == 1000
        and RUN.fullmatch(run)
        and image == IMAGE
        and HEX.fullmatch(expected),
        "exact_native_QA_scope_required",
    )
    require(
        root == ROOT and root.resolve(strict=True) == root,
        "exact_native_QA_source_root_required",
    )
    # Direct clean -E/-s launches put only tools/checks on sys.path. Import the
    # reviewed ops package from this explicit canonical source root, never from
    # ambient PYTHONPATH or the caller's working directory.
    sys.path.insert(0, str(root))
    from retirement_fixture.installer_rehearsal_resources import Rehearsal

    fixture = Rehearsal(root, run, image, expected)
    children, previous = [], {}
    cleaning = False
    report = {
        "status": "failed",
        "run": run,
        "source_sha256": expected,
        "image_id": image,
        "production_mutations": 0,
        "cleanup": False,
        "encrypted_retention_proven": False,
        "total_host_restore_proven": False,
    }

    def cancel(number, frame):
        if not cleaning:
            raise RuntimeError("rehearsal_cancelled")

    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
        previous[number] = signal.getsignal(number)
        signal.signal(number, cancel)
    try:
        report["phase"] = "prepare"
        setup = fixture.prepare()
        require(
            setup.get("source_sha256") == expected
            and HEX.fullmatch(setup.get("install_profile_sha256", ""))
            and HEX.fullmatch(setup.get("code_manifest_sha256", "")),
            "fixture_source_or_profile_mismatch",
        )
        # Compatibility evidence only: the final reviewed source pin must include
        # io.aqua.qa-run linkage, and helper cleanup must inspect actual resources.
        require(
            setup.get("child_ownership_linked") is True,
            "QA_child_ownership_linkage_required",
        )
        report["phase"] = "install_keeper"
        keeper_until = time.monotonic() + 285
        keeper = start(
            fixture.stage,
            run,
            "install.py",
            ["--execute", "--profile-sha256", setup["install_profile_sha256"]],
            children,
        )
        with receive(keeper, 16384, time.monotonic() + 185, first_line=True) as output:
            receipt = decoded(output.getvalue())
        require(
            receipt.get("status") == "installed_writers_still_stopped"
            and receipt.get("maintenance_held") is True
            and all(
                receipt.get(key) is False
                for key in (
                    "writers_resumed",
                    "cron_resumed",
                    "initial_encrypted_retention_proven",
                    "schema9_fallback_proven",
                    "total_host_restore_supported",
                )
            )
            and HEX.fullmatch(receipt.get("export_profile_sha256", ""))
            and keeper.poll() is None,
            "installer_keeper_not_held",
        )
        # Cleanup may clear APPEND only on the inode captured while the actual
        # installer still holds maintenance, never on a cleanup-time substitute.
        fixture.capture_installed_checkpoint()
        report["installer_keeper_held"] = True
        report["phase"] = "head"
        pin = receipt["export_profile_sha256"]
        with command(
            fixture.stage,
            run,
            "head",
            pin,
            children,
            min(keeper_until, time.monotonic() + 30),
            16384,
        ) as output:
            head = checked_head(decoded(output.getvalue()), receipt, expected, image)
        require(keeper.poll() is None, "keeper_lost_before_export")
        report["phase"] = "export"
        with command(
            fixture.stage,
            run,
            "export",
            pin,
            children,
            min(keeper_until, time.monotonic() + 125),
            MAX_ARCHIVE,
        ) as output:
            report["archive"] = checked_archive(output, head)
        require(
            keeper.poll() is None and time.monotonic() < keeper_until,
            "keeper_lost_after_export",
        )
        report["phase"] = "credential_denials"
        denials = fixture.probe_denials()
        require(
            set(denials) == {"wrong_password_rejected", "app_role_authority_denied"}
            and all(value is True for value in denials.values()),
            "credential_denial_not_proven",
        )
        report.update(denials)
        require(
            keeper.poll() is None and time.monotonic() < keeper_until,
            "keeper_lost_before_release",
        )
        report["phase"] = "release"
        require(
            os.write(keeper.stdin.fileno(), b"release\n") == 8,
            "keeper_release_short_write",
        )
        keeper.stdin.close()
        with receive(keeper, 16384, min(keeper_until, time.monotonic() + 20)) as output:
            final = decoded(output.getvalue())
        expected_final = dict(receipt)
        del expected_final["maintenance_held"]
        require(final == expected_final, "installer_final_receipt_changed")
        report["keeper_released_after_checks"] = True
        report["phase"] = "genesis_recovery_CLI"
        recovery_pin = fixture.prepare_recovery(head, setup["code_manifest_sha256"])
        recovery = start(
            fixture.stage,
            run,
            "recover.py",
            [
                "--execute",
                "--profile-sha256",
                recovery_pin,
                "--protected-sha256",
                head["protected_chain_sha256"],
            ],
            children,
        )
        recovery.stdin.close()
        # This remains inside the original 300-second fixture work budget. The
        # real CLI's 120-second alarm and unchanged cleanup limits still apply.
        with receive(
            recovery, 16384, min(fixture.deadline, time.monotonic() + 125)
        ) as output:
            report["genesis_recovery_cli"] = checked_recovery(
                decoded(output.getvalue()),
                head,
            )
        report["status"] = "passed"
    except (Exception, KeyboardInterrupt) as error:
        # Never stringify exceptions: child/SQL errors can contain credentials.
        report.update(public_error(error))
    finally:
        cleaning = True
        stopped = [stop(process) for process in reversed(children)]
        report["controllers_exited"] = all(stopped)
        try:
            if all(stopped):
                cleanup = fixture.cleanup()
                report["cleanup"] = cleanup.get("complete") is True
            else:
                report["cleanup"] = False
        except Exception:
            report["cleanup"] = False
        if not report["cleanup"] or not report["controllers_exited"]:
            report["status"] = "failed"
        for number, handler in previous.items():
            signal.signal(number, handler)
    print(json.dumps(report, sort_keys=True))
    return int(report["status"] != "passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--run", default="")
    parser.add_argument("--image", default=IMAGE)
    parser.add_argument("--source-sha256", default="")
    args = parser.parse_args()
    if not args.execute:
        print(
            json.dumps(
                {
                    "status": "prepared_only",
                    "Docker_actions": 0,
                    "private_reads": 0,
                    "writes": 0,
                    "native_execution_requires_reviewed_child_lineage": True,
                }
            )
        )
        return 0
    try:
        return execute(ROOT, args.run, args.image, args.source_sha256)
    except (Exception, KeyboardInterrupt) as error:
        print(
            json.dumps(
                {
                    "status": "failed",
                    "phase": "preflight",
                    **public_error(error),
                }
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
