"""Concrete source-bound native restore callback; no activity on construction."""

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shlex
import secrets
import signal
import sys
import types

from adapter_package import (
    REMOTE,
    manifest,
    pack,
    packet,
    read_packet,
    source_files,
    unpack,
)
from authority_support import host

FIELDS = (
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
)


class NativeSQLAdapter:
    """Compile only manifest-verified controller transport bytes, then request SQL."""

    def __init__(self, directory, expected_manifest_sha256, image):
        self.directory = Path(directory)
        self.manifest_sha256, self.image = expected_manifest_sha256, image
        self.last_run = None
        self.last_receipt = None
        files = source_files(directory)
        self.package = pack(files)
        verified = unpack(self.package, expected_manifest_sha256)
        # The subprocess transport is loaded from already verified source bytes.
        self.process = types.ModuleType("verified_restore_process")
        exec(
            compile(
                verified["verifier_process.py"], "/verified/verifier_process.py", "exec"
            ),
            self.process.__dict__,
        )

    def preflight(self, expected):
        expected.checked()
        if (
            expected.restore_verifier_sha256 != self.manifest_sha256
            or expected.runtime_image != self.image
            or hashlib.sha256(manifest(source_files(self.directory))).hexdigest()
            != self.manifest_sha256
        ):
            raise ValueError("verifier_source_or_image_changed_before_call")

    def __call__(self, dump, expected, seconds):
        self.preflight(expected)
        public = {name: getattr(expected, name) for name in FIELDS}
        chain = expected.verification_chain
        if (
            type(chain) is not bytes
            or hashlib.sha256(chain).hexdigest() != expected.protected_chain_sha256
            or chain[-208:].hex() != expected.head_hex
            or not 45 < seconds <= 120
        ):
            raise ValueError("verifier_checked_public_chain_or_budget_required")
        self.last_run = "aqua-authority-verify-" + secrets.token_hex(12)
        data = packet(
            {
                "expected": public,
                "image": self.image,
                "seconds": seconds,
                "run": self.last_run,
            },
            self.package,
            dump,
            chain,
        )
        # Only public source/dump/head/chain cross SSH: no archive/key members.
        command = host.ssh_command(
            [
                shlex.join(
                    [
                        "/usr/bin/python3",
                        "-E",
                        "-s",
                        "-B",
                        "-c",
                        REMOTE,
                        self.manifest_sha256,
                    ]
                )
            ]
        )
        code, raw = self.process.bounded(command, data, seconds=seconds, maximum=16384)
        try:
            self.last_receipt = json.loads(raw)
        except (ValueError, UnicodeError):
            self.last_receipt = {
                "status": "failed",
                "run": self.last_run,
                "category": "unreadable_verifier_response",
            }
        if code:
            raise ValueError("actual_disposable_restore_did_not_pass")
        result = self.last_receipt
        if (
            result.get("status") != "passed"
            or result.get("mode") != "actual_disposable_restore"
            or result.get("verifier_source_sha256") != self.manifest_sha256
            or result.get("cleanup") != "removed_and_absence_confirmed"
            or result.get("remaining_ids") != []
        ):
            raise ValueError("actual_disposable_restore_receipt_invalid")
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--image")
    args = parser.parse_args()
    files = source_files(Path(__file__).parent / "sql-verifier")
    pin = hashlib.sha256(manifest(files)).hexdigest()
    if args.execute:
        if args.manifest_sha256 != pin or args.image is None:
            parser.error("explicit_execute_requires_reviewed_source_manifest_and_image")
        adapter = NativeSQLAdapter(
            Path(__file__).parent / "sql-verifier", pin, args.image
        )
        signal.alarm(15)
        header, source, dump, chain = read_packet(sys.stdin.buffer)
        signal.alarm(0)
        if source != adapter.package or header.get("image") != args.image:
            raise ValueError("verifier_explicit_input_source_or_image_mismatch")
        from authority_contract import Expected

        expected = replace(Expected(**header["expected"]), verification_chain=chain)
        with adapter.process.Cancellation():
            result = adapter(dump, expected, header["seconds"])
        print(json.dumps(result, sort_keys=True))
        return
    if args.manifest_sha256 is not None or args.image is not None:
        parser.error("source_or_image_requires_explicit_execute")
    print(
        json.dumps(
            {
                "status": "prepared_only",
                "source_manifest_sha256": pin,
                "Docker_SSH_DB_actions": 0,
                "key_reads": 0,
                "writes": 0,
                "explicit_execution": "NativeSQLAdapter callback, only after ROOT review",
            }
        )
    )


if __name__ == "__main__":
    main()
