"""Public RAM archives and modeled transports only; no real SSH/age/keys."""

from copy import deepcopy
from dataclasses import replace
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch

import authority_bridge as bridge
from authority_test_fixtures import RECIPIENT, STAGE, FakeTransport, fixture, verifier


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.expected, self.contents, self.profile, self.raw, self.head = fixture()

    def test_reviewed_primitive_bytes_and_AGE_SSH_pins_are_preserved(self):
        root = Path(bridge.__file__).parent
        manifest = json.loads((root / "vendor-manifest.json").read_text())
        self.assertEqual(len(manifest), 5)
        for name, pin in manifest.items():
            self.assertEqual(
                bridge.sha((root / "vendor" / name).read_bytes()), pin["sha256"]
            )
        self.assertEqual(
            bridge.stream.AGE_SHA256,
            "4012dfc2725883beafb710894af4f599b7a94f8c8e0f51f02cc96ab8df33915e",
        )
        self.assertEqual(
            bridge.host.HOST_FINGERPRINT,
            "SHA256:v+WP4CGClEGX9cg2x9Gh+Lvcc17A0mV/+XgTBxlGqb0",
        )

    def test_default_CLI_has_zero_server_private_key_export_or_write_actions(self):
        result = subprocess.run(
            [sys.executable, "-B", str(Path(bridge.__file__))],
            capture_output=True,
            check=True,
            timeout=5,
        )
        value = json.loads(result.stdout)
        self.assertEqual(value["status"], "prepared_only")
        self.assertEqual(
            [
                value[k]
                for k in ("server_actions", "private_key_reads", "exports", "writes")
            ],
            [0] * 4,
        )
        self.assertFalse(value["production_CLI_enabled"])

    def test_same_old_archive_cannot_select_its_own_trusted_head(self):
        old = replace(
            self.expected, head_hex=self.contents["checkpoints.bin"][:208].hex()
        )
        with self.assertRaises(ValueError):
            bridge.verify_ram(self.raw, old, verifier, 20)

    def test_both_keys_chain_and_pinned_runtime_are_required(self):
        value = bridge.verify_ram(self.raw, self.expected, verifier, 20)
        self.assertTrue(value["full_chain_and_both_keys_verified"])
        self.assertEqual(value["sql_verifier_mode"], "synthetic_model")
        for changed in (
            replace(self.expected, runtime_image="sha256:" + "f" * 64),
            replace(self.expected, protected_chain_sha256="f" * 64),
        ):
            with (
                self.subTest(changed=changed.runtime_image),
                self.assertRaises(bridge.stream.BackupError),
            ):
                bridge.verify_ram(self.raw, changed, verifier, 20)

    def test_changed_key_even_with_rehashed_member_is_rejected(self):
        contents, profile = deepcopy(self.contents), deepcopy(self.profile)
        contents["identity.key"] = b"z" * 32
        profile["files"]["identity.key"] = bridge.sha(contents["identity.key"])
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w") as tar:
            for name, raw in [
                ("profile.json", json.dumps(profile).encode()),
                *contents.items(),
            ]:
                item = tarfile.TarInfo(name)
                item.size = len(raw)
                tar.addfile(item, io.BytesIO(raw))
        with self.assertRaises(ValueError):
            bridge.verify_ram(output.getvalue(), self.expected, verifier, 20)

    def test_restore_callback_missing_or_misbound_or_incomplete_is_not_green(self):
        with self.assertRaises(bridge.stream.BackupError):
            bridge.verify_ram(self.raw, self.expected, None, 20)
        for key, value in (
            ("dump_sha256", "f" * 64),
            ("head_sha256", "f" * 64),
            ("verifier_source_sha256", "f" * 64),
            ("authority_tables", ["control"]),
            ("original_pages_and_floors_verified", False),
            ("remaining_ids", ["owned-resource"]),
            ("mode", "caller_boolean"),
        ):

            def altered(*args):
                return {**verifier(*args), key: value}

            with self.subTest(key=key), self.assertRaises(bridge.stream.BackupError):
                bridge.verify_ram(self.raw, self.expected, altered, 20)

    def test_metadata_rejects_expired_unstopped_forged_head_and_total_host_claims(self):
        for key, value in (
            ("head_hex", "0" * 416),
            ("sequence", True),
            ("holders_stopped", {"web": "absence_confirmed"}),
            ("total_host_restore_supported", True),
            ("maintenance_expires_utc", "2000-01-01T00:00:00+00:00"),
            ("maintenance_receipt_sha256", "f" * 64),
        ):
            with self.subTest(key=key), self.assertRaises(bridge.stream.BackupError):
                bridge.metadata({**self.head, key: value}, self.expected)

    def test_transport_is_closed_to_arbitrary_stage_or_action(self):
        with patch.object(
            bridge.host, "ssh_command", side_effect=lambda args: args
        ) as ssh:
            command = bridge.remote_command(STAGE, "export", self.expected)
            self.assertIn("--profile-sha256", command[0])
            self.assertIn(self.expected.exporter_sha256, command[0])
            for stage, action in (
                ("/srv/bank-ai", "export"),
                (STAGE + "/../other", "head"),
                (STAGE, "shell"),
            ):
                with self.assertRaises(bridge.stream.BackupError):
                    bridge.remote_command(stage, action, self.expected)
            self.assertEqual(ssh.call_count, 1)

    def modeled_collect(self, directory, transport=None, verify=verifier):
        transport = transport or FakeTransport(self.raw, self.head)
        with (
            patch.object(
                bridge.host, "private_directory", return_value=("directory", "ACL")
            ),
            patch.object(bridge.host, "backup_recipient", return_value=RECIPIENT),
        ):
            result = bridge.collect(
                STAGE,
                directory,
                Path(directory) / "not-a-real-key",
                [RECIPIENT],
                self.expected,
                verify,
                transport=transport,
            )
        return result, transport

    def test_modeled_capture_and_recovered_copy_never_claim_offhost_or_RPO0(self):
        with tempfile.TemporaryDirectory() as directory:
            record, transport = self.modeled_collect(directory)
            self.assertEqual(record["status"], "modeled_only")
            cipher = Path(directory) / record["encrypted_file"]
            recovered = bridge.verify_recovered(
                cipher,
                Path(directory) / "modeled-key",
                self.expected,
                record,
                verifier,
                transport=transport,
            )
            for value in (record, recovered):
                self.assertFalse(value["globally_latest_accepted_head_proven"])
                self.assertFalse(value["total_host_restore_supported"])
                self.assertFalse(value["independent_storage_proven"])
            self.assertEqual(len(list(Path(directory).iterdir())), 1)
            self.assertNotIn(b"PGDMP", cipher.read_bytes())
            self.assertNotIn(self.contents["identity.key"], cipher.read_bytes())

    def test_resolved_checkout_alias_cannot_receive_an_authority_backup(self):
        transport = FakeTransport(self.raw, self.head)
        with patch.object(bridge.host, "backup_recipient") as key_read:
            with self.assertRaisesRegex(
                bridge.stream.BackupError, "inside_resolved_checkout"
            ):
                bridge.collect(
                    STAGE,
                    bridge.host.PROJECT.resolve(),
                    Path("unused"),
                    [RECIPIENT],
                    self.expected,
                    verifier,
                    transport=transport,
                )
        self.assertEqual(transport.calls, [])
        key_read.assert_not_called()

    def test_changed_after_head_refuses_capture_and_removes_only_owned_pending(self):
        transport = FakeTransport(self.raw, self.head)
        original = transport.head
        calls = []

        def changed(*args):
            result = original(*args)
            calls.append(1)
            if len(calls) == 2:
                result["maintenance_nonce"] = "f" * 32
            return result

        transport.head = changed
        with tempfile.TemporaryDirectory() as directory:
            sentinel = Path(directory) / "keep.age"
            sentinel.write_bytes(b"sentinel")
            with self.assertRaises(bridge.stream.BackupError):
                self.modeled_collect(directory, transport)
            self.assertEqual([p.name for p in Path(directory).iterdir()], ["keep.age"])

    def test_mismatched_authenticated_export_digest_refuses_and_cleans_pending(self):
        transport = FakeTransport(self.raw, self.head)
        encrypt = transport.encrypt

        def wrong(*args):
            return {**encrypt(*args), "plaintext_sha256": "f" * 64}

        transport.encrypt = wrong
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(bridge.stream.BackupError):
                self.modeled_collect(directory, transport)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_cipher_replacement_during_verification_is_not_published_or_deleted(self):
        transport = FakeTransport(self.raw, self.head)

        def swapped(ciphertext, *args):
            ciphertext.unlink()
            ciphertext.write_bytes(b"FOREIGN-CIPHERTEXT-KEEP")
            ciphertext.chmod(0o600)
            return self.raw

        transport.decrypt = swapped
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(bridge.stream.BackupError, "identity_changed"):
                self.modeled_collect(directory, transport)
            files = list(Path(directory).iterdir())
            self.assertEqual(len(files), 1)
            self.assertTrue(files[0].name.startswith(".pending-authority-"))
            self.assertEqual(files[0].read_bytes(), b"FOREIGN-CIPHERTEXT-KEEP")


if __name__ == "__main__":
    unittest.main()
