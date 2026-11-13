"""Source-checked explicit isolated execution; default touches no Docker or DB."""

import hashlib
import io
import json
import os
import re
import secrets
import stat
import sys
import tarfile
from uuid import UUID

from verifier_process import (
    Cancellation,
    DOCKER,
    Failure,
    PROBE_CODES,
    PROBE_STAGES,
    bounded,
)
from verifier_resources import RUN, Resources
from verifier_setup import CATALOG, initialize, restore, sql

MAX_CHAIN = 250001 * 208
PUBLIC_FIELDS = {
    "installation_id",
    "identity_key_id",
    "key_commitment",
    "public_key",
    "runtime_image",
    "source_sha256",
    "profile_sha256",
    "exporter_sha256",
    "restore_verifier_sha256",
    "maintenance_nonce",
    "maintenance_receipt_sha256",
    "protected_chain_sha256",
    "head_hex",
}
BOOTSTRAP = """import io,json,os,pathlib,sys,tarfile
try:
 raw=sys.stdin.buffer.read(68157441);assert 0<len(raw)<=68157440
 root=pathlib.Path('/checks')
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
  for m in archive.getmembers():
   p=pathlib.PurePosixPath(m.name);assert m.isfile() and not p.is_absolute() and '..' not in p.parts and not any(x.startswith('.') for x in p.parts) and m.size<=67108864 and (p.suffix in {'.py','.psql'} or m.name in {'public.json','chain.bin'})
  archive.extractall(root,filter='data')
 os.chdir(root);sys.path.insert(0,str(root));sys.path.insert(0,str(root/'retirement'))
 os.execv(sys.executable,[sys.executable,'-B',str(root/'verifier_probe.py'),sys.argv[1]])
except Exception:
 print(json.dumps({'status':'failed','probe_subphase':'bootstrap','probe_failure_code':'unclassified_failure'}))
 raise SystemExit(1) from None
"""


def checked_request(expected, chain, image, manifest):
    if (
        type(expected) is not dict
        or set(expected) != PUBLIC_FIELDS
        or not re.fullmatch(r"sha256:[a-f0-9]{64}", image)
        or expected["runtime_image"] != image
        or expected["restore_verifier_sha256"] != manifest
    ):
        raise Failure("verifier_public_request_invalid")
    for name in ("installation_id", "identity_key_id"):
        if str(UUID(expected[name])) != expected[name]:
            raise Failure("verifier_UUID_invalid")
    for name in PUBLIC_FIELDS - {
        "installation_id",
        "identity_key_id",
        "runtime_image",
        "head_hex",
        "maintenance_nonce",
    }:
        if not isinstance(expected[name], str) or not re.fullmatch(
            r"[a-f0-9]{64}", expected[name]
        ):
            raise Failure("verifier_public_hex_invalid")
    if (
        not re.fullmatch(r"[a-f0-9]{416}", expected["head_hex"])
        or not re.fullmatch(r"[a-f0-9]{32}", expected["maintenance_nonce"])
        or type(chain) is not bytes
        or not 208 <= len(chain) <= MAX_CHAIN
        or len(chain) % 208
        or hashlib.sha256(chain).hexdigest() != expected["protected_chain_sha256"]
        or chain[-208:].hex() != expected["head_hex"]
    ):
        raise Failure("verifier_public_chain_invalid")


def probe_package(files, expected, chain, dump_sha):
    output = io.BytesIO()
    request = json.dumps(
        {"expected": expected, "dump_sha256": dump_sha}, sort_keys=True
    ).encode()
    with tarfile.open(fileobj=output, mode="w") as package:
        for name, raw in [
            *sorted(files.items()),
            ("public.json", request),
            ("chain.bin", chain),
        ]:
            item = tarfile.TarInfo(name)
            item.size, item.mode, item.uid, item.gid = len(raw), 0o600, 1000, 1000
            package.addfile(item, io.BytesIO(raw))
    value = output.getvalue()
    if len(value) > 68157440:
        raise Failure("verifier_public_probe_payload_bound")
    return value


def probe_run(resources, probe, payload, report):
    """Same bounded start; only fixed tiny failure JSON may leave RAM."""
    code, raw = bounded(
        DOCKER + ["start", "--attach", "--interactive", probe],
        data=payload,
        seconds=resources.budget.remaining(),
        maximum=65536,
    )
    if code:
        try:
            result = json.loads(raw)
            if (
                type(result) is dict
                and set(result) == {"status", "probe_subphase", "probe_failure_code"}
                and result["status"] == "failed"
                and type(result["probe_subphase"]) is str
                and result["probe_subphase"] in PROBE_STAGES
                and type(result["probe_failure_code"]) is str
                and result["probe_failure_code"] in PROBE_CODES
            ):
                report["probe_subphase"] = result["probe_subphase"]
                report["probe_failure_code"] = result["probe_failure_code"]
        except (ValueError, TypeError):
            pass
        raise Failure("verifier_docker_failed")
    return json.loads(raw)


def execute(files, dump, chain, expected, image, manifest, seconds, run=None):
    """No original authority or signing/HMAC material is accepted by this API."""
    checked_request(expected, chain, image, manifest)
    if (
        type(dump) is not bytes
        or not 0 < len(dump) <= 128 * 1024**2
        or not dump.startswith(b"PGDMP")
    ):
        raise Failure("verifier_dump_bound_or_format_invalid")
    if sys.platform != "linux" or os.geteuid() != 1000 or not 35 < seconds <= 120:
        raise Failure("verifier_native_UID1000_and_cleanup_budget_required")
    binary, socket = os.stat("/usr/bin/docker"), os.lstat("/var/run/docker.sock")
    if (
        not stat.S_ISREG(binary.st_mode)
        or binary.st_uid != 0
        or binary.st_mode & 0o022
        or not stat.S_ISSOCK(socket.st_mode)
        or socket.st_uid != 0
    ):
        raise Failure("verifier_Docker_endpoint_invalid")
    name = "aqua-authority-verify-" + secrets.token_hex(12)
    if run is not None:
        if not RUN.fullmatch(run):
            raise Failure("verifier_fresh_run_scope_invalid")
        name = run
    resources = Resources(name, image, seconds - 30)
    report = {
        "status": "failed",
        "phase": "image_inspect",
        "mode": "actual_disposable_restore",
        "run": name,
        "dump_sha256": hashlib.sha256(dump).hexdigest(),
        "head_sha256": hashlib.sha256(bytes.fromhex(expected["head_hex"])).hexdigest(),
        "runtime_image": image,
        "source_sha256": expected["source_sha256"],
        "verifier_source_sha256": manifest,
        "signing_or_HMAC_key_inputs": False,
        "plaintext_dump_files": 0,
        "production_actions": 0,
    }
    with Cancellation() as cancellation:
        try:
            if (
                resources.call("image", "inspect", image, "--format={{.Id}}")
                .decode()
                .strip()
                != image
            ):
                raise Failure("verifier_immutable_image_mismatch")
            report["phase"] = "initialize"
            before = initialize(resources, files, expected)
            report["phase"] = "restore"
            report["full_dump_inventory_sha256"] = restore(resources, dump)
            report["phase"] = "catalog"
            after = sql(resources, CATALOG, database="aqua_retirement").strip()
            if before != after or not re.fullmatch(rb"[a-f0-9]{64}", after):
                raise Failure("verifier_trusted_source_catalog_changed")
            report["phase"] = "probe_create"
            probe = resources.create(
                "probe",
                ["-u", "-c", BOOTSTRAP, str(max(1, int(resources.budget.remaining())))],
            )
            report["phase"] = "probe_run"
            result = probe_run(
                resources,
                probe,
                probe_package(files, expected, chain, report["dump_sha256"]),
                report,
            )
            if (
                result.get("status") != "passed"
                or result.get("head_sha256") != report["head_sha256"]
                or result.get("dump_sha256") != report["dump_sha256"]
            ):
                raise Failure("verifier_full_SQL_comparison_not_passed")
            report.update(result)
            report["trusted_source_catalog_sha256"] = after.decode()
            report["phase"] = "completed"
        except (Exception, KeyboardInterrupt) as error:
            code = (
                error.args[0]
                if type(error) is Failure and len(error.args) == 1
                else None
            )
            report["failure_code"] = (
                code
                if type(code) is str
                and code
                in {"verifier_restore_foreign_key_violation", "verifier_docker_failed"}
                else "unclassified_failure"
            )
            report["status"] = "failed"
            report["category"] = "isolated_authority_restore_failed"
        finally:
            cancellation.cleaning = True
            remaining = resources.cleanup()
            report["remaining_ids"] = remaining
            report["cleanup"] = (
                "unconfirmed" if remaining else "removed_and_absence_confirmed"
            )
            if remaining or cancellation.cancelled:
                report["status"] = "failed"
    return report


def main():
    if sys.argv[1:]:
        raise Failure("verifier_explicit_source_checked_adapter_required")
    print(
        json.dumps(
            {
                "status": "prepared_only",
                "Docker_actions": 0,
                "DB_actions": 0,
                "private_reads": 0,
                "writes": 0,
                "execution_requires_root_reviewed_adapter": True,
            }
        )
    )


if __name__ == "__main__":
    main()
