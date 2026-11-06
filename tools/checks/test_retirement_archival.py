"""Private archival boundary attacks using public synthetic keys and no DB."""

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ops.retirement import archive, backup_protocol, recovery_driver
from retirement.fingerprints import IdentityKey
from retirement.checkpoint import ProtectedFile
from retirement.interlock import RetirementUnavailable
from retirement.publisher import signed_record


def fixture():
    key = IdentityKey("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", b"k" * 32)
    private = Ed25519PrivateKey.from_private_bytes(b"s" * 32)
    public = private.public_key().public_bytes_raw()
    installation = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    genesis = signed_record(
        private,
        installation=installation,
        key_id=key.key_id,
        sequence=0,
        digest=bytes(32),
        previous=bytes(32),
        commitment=key.commitment,
    )
    next_head = signed_record(
        private,
        installation=installation,
        key_id=key.key_id,
        sequence=1,
        digest=b"d" * 32,
        previous=hashlib.sha256(genesis).digest(),
        commitment=key.commitment,
    )
    contents = {
        "authority.dump": b"PGDMPsynthetic-ledger-not-a-real-database",
        "checkpoints.bin": genesis + next_head,
        "identity.key": b"k" * 32,
        "signing.key": b"s" * 32,
    }
    profile = {
        "schemaVersion": 1,
        "installation_id": installation,
        "identity_key_id": key.key_id,
        "key_commitment": key.commitment.hex(),
        "public_key": public.hex(),
        "runtime_image": "sha256:" + "a" * 64,
        "source_sha256": "b" * 64,
        "files": {
            name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()
        },
    }
    return contents, profile, next_head


def rehash(contents, profile):
    profile["files"] = {
        name: hashlib.sha256(raw).hexdigest() for name, raw in contents.items()
    }


class ArchiveGuards(unittest.TestCase):
    def test_normal_roundtrip_checks_keys_chain_and_expected_protected_head(self):
        contents, profile, head = fixture()
        checked = archive.checked(contents, profile, head)
        target = io.BytesIO()
        archive.write(checked, target)
        restored = archive.read(target.getvalue(), head)
        self.assertEqual(restored.contents, contents)
        self.assertEqual(restored.profile, profile)
        self.assertNotIn(repr(contents["identity.key"]), repr(restored))
        self.assertNotIn(repr(contents["signing.key"]), repr(restored))

    def test_self_consistent_old_or_foreign_head_cannot_satisfy_expected_head(self):
        contents, profile, head = fixture()
        for expected in (
            contents["checkpoints.bin"][:208],
            bytes(208),
            head[:-1] + b"x",
        ):
            with self.subTest(expected_hash=hashlib.sha256(expected).hexdigest()):
                with self.assertRaises(ValueError):
                    archive.checked(contents, profile, expected)
        contents["checkpoints.bin"] = contents["checkpoints.bin"][:208]
        rehash(contents, profile)
        with self.assertRaises(ValueError):
            archive.checked(contents, profile, head)

    def test_rehashed_wrong_keys_broken_signatures_and_chain_do_not_become_valid(self):
        for field in ("identity.key", "signing.key", "checkpoints.bin"):
            contents, profile, head = fixture()
            contents[field] = contents[field][:-1] + bytes([contents[field][-1] ^ 1])
            rehash(contents, profile)
            with self.subTest(field=field):
                with self.assertRaises((ValueError, RuntimeError)):
                    archive.checked(contents, profile, head)

    def test_bad_manifest_unknown_file_and_non_dump_rejected_before_output(self):
        for mutation in ("manifest", "extra", "dump", "tag", "source"):
            contents, profile, head = fixture()
            if mutation == "manifest":
                profile["files"]["identity.key"] = "0" * 64
            if mutation == "extra":
                contents["secret.env"] = b"never accepted"
            if mutation == "dump":
                contents["authority.dump"] = b"not a pg_dump"
            if mutation == "tag":
                profile["runtime_image"] = "runtime:latest"
            if mutation == "source":
                profile["source_sha256"] = "PENDING"
            with self.subTest(mutation=mutation):
                with self.assertRaises(ValueError):
                    archive.checked(contents, profile, head)

    def test_archive_paths_links_duplicate_members_and_capacity_fail_closed(self):
        _, _, head = fixture()
        for variant in ("path", "link", "duplicate", "capacity"):
            output = io.BytesIO()
            with tarfile.open(fileobj=output, mode="w") as tar:
                info = tarfile.TarInfo(
                    "../identity.key" if variant == "path" else "identity.key"
                )
                info.size = 33 if variant == "capacity" else 32
                if variant == "link":
                    info.type, info.linkname, info.size = (
                        tarfile.SYMTYPE,
                        "/etc/passwd",
                        0,
                    )
                tar.addfile(info, io.BytesIO(b"x" * info.size))
                if variant == "duplicate":
                    tar.addfile(info, io.BytesIO(b"x" * 32))
            with self.subTest(variant=variant):
                with self.assertRaises(ValueError):
                    archive.read(output.getvalue(), head)

    def test_missing_and_duplicate_profile_values_fail_closed(self):
        contents, profile, head = fixture()
        for changed in (
            {key: value for key, value in profile.items() if key != "public_key"},
            {**profile, "latest": True},
        ):
            with self.assertRaises(ValueError):
                archive.checked(contents, changed, head)
        target = io.BytesIO()
        with tarfile.open(fileobj=target, mode="w") as tar:
            raw = json.dumps(profile)[:-1].encode() + b',"schemaVersion":1}'
            for name, raw in [("profile.json", raw), *contents.items()]:
                info = tarfile.TarInfo(name)
                info.size = len(raw)
                tar.addfile(info, io.BytesIO(raw))
        with self.assertRaises(ValueError):
            archive.read(target.getvalue(), head)

    def test_total_host_restore_remains_closed_even_for_valid_old_bundle_or_boolean(
        self,
    ):
        contents, profile, head = fixture()
        for arguments in (
            {"verified": True},
            {"backup_age_days": 0},
            {"head": head},
            {"bundle": archive.checked(contents, profile, head)},
        ):
            with self.assertRaises(RetirementUnavailable):
                recovery_driver.total_host(**arguments)

    def test_default_recovery_has_no_private_reads_or_database_actions(self):
        root = Path(__file__).resolve().parents[2]
        completed = subprocess.run(
            [sys.executable, str(root / "ops/retirement/recovery_driver.py")],
            capture_output=True,
            timeout=5,
            check=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(
            (report["private_reads"], report["pool_opens"], report["writes"]), (0, 0, 0)
        )
        self.assertFalse(report["total_host_authority_restore_supported"])


class CaptureGuards(unittest.TestCase):
    def test_dump_is_inside_same_gate_and_all_failure_paths_release_or_poison(self):
        contents, profile, _ = fixture()
        for fault in (None, "dump", "unlock", "pending"):

            class Connection:
                autocommit = True
                info = SimpleNamespace(transaction_status=0)
                locked = False
                closed = False

                def execute(self, statement, values=()):
                    if "rolconnlimit" in statement:
                        row = (
                            "aqua_retirement",
                            "aqua_retirement_recovery",
                            "aqua_retirement_recovery",
                            False,
                            False,
                            False,
                            False,
                            False,
                            False,
                            1,
                        )
                    elif statement.startswith("SHOW "):
                        row = ("on",)
                    elif "pg_try_advisory_lock" in statement:
                        self.locked = True
                        row = (True,)
                    elif "pg_advisory_unlock" in statement:
                        self.locked = False
                        row = (fault != "unlock",)
                    elif "pg_locks" in statement:
                        row = (0,)
                    elif "retirement.checkpoint()" in statement:
                        row = (
                            profile["installation_id"],
                            profile["identity_key_id"],
                            bytes.fromhex(profile["key_commitment"]),
                            1,
                            b"d" * 32,
                            1,
                            b"d" * 32,
                            int(fault == "pending"),
                        )
                    else:
                        raise AssertionError("unexpected_operator_query")
                    return SimpleNamespace(fetchone=lambda: row)

                def close(self):
                    self.closed = True

            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as raw:
                directory = Path(raw).resolve()
                path = directory / "checkpoints.bin"
                path.write_bytes(contents["checkpoints.bin"])
                path.chmod(0o600)
                protected = ProtectedFile(
                    path,
                    owner_uid=os.geteuid(),
                    public_key=bytes.fromhex(profile["public_key"]),
                    installation=profile["installation_id"],
                    key_id=profile["identity_key_id"],
                    commitment=bytes.fromhex(profile["key_commitment"]),
                )
                conn = Connection()
                called = []

                def dump():
                    self.assertTrue(conn.locked)
                    called.append(True)
                    if fault == "dump":
                        raise RuntimeError("fixture_dump_failure")
                    return contents["authority.dump"]

                with patch("retirement.checkpoint.append_only", return_value=True):
                    if fault is None:
                        bundle = backup_protocol.capture(
                            conn,
                            protected,
                            contents["identity.key"],
                            contents["signing.key"],
                            dump=dump,
                            runtime_image=profile["runtime_image"],
                            source_sha256=profile["source_sha256"],
                        )
                        self.assertEqual(bundle.contents, contents)
                    else:
                        with self.assertRaises(RuntimeError):
                            backup_protocol.capture(
                                conn,
                                protected,
                                contents["identity.key"],
                                contents["signing.key"],
                                dump=dump,
                                runtime_image=profile["runtime_image"],
                                source_sha256=profile["source_sha256"],
                            )
                self.assertFalse(conn.locked)
                self.assertEqual(bool(called), fault != "pending")
                self.assertEqual(conn.closed, fault == "unlock")


if __name__ == "__main__":
    unittest.main()
