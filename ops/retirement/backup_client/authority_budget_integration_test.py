"""Fake-clock, synthetic archive/transport integration; no SSH, age or SQL."""

from contextlib import ExitStack
from pathlib import Path
import os
import shlex
import tempfile
import unittest
from unittest.mock import patch

import authority_bridge as bridge
from authority_budget import BudgetDenied, Deadline
from authority_contract import ExporterRoute
from authority_sql_adapter import NativeSQLAdapter
from authority_test_fixtures import RECIPIENT, STAGE, FakeTransport, fixture, verifier
import authority_verify as verification


class Clock:
    def __init__(self, now=0):
        self.now = now

    def __call__(self):
        return self.now


class TimedTransport(FakeTransport):
    def __init__(self, raw, metadata, clock, *, costs=None):
        super().__init__(raw, metadata)
        self.clock, self.caps = clock, []
        self.costs = costs or {}

    def spend(self, operation, seconds):
        self.caps.append((operation, seconds))
        self.clock.now += self.costs.get(operation, 0)

    def head(self, stage, expected, *, seconds=20):
        self.spend("head", seconds)
        return super().head(stage, expected)

    def encrypt(self, stage, expected, recipients, destination, seconds):
        self.spend("encrypt", seconds)
        return super().encrypt(stage, expected, recipients, destination, seconds)

    def decrypt(self, ciphertext, identity, seconds):
        self.spend("decrypt", seconds)
        return super().decrypt(ciphertext, identity, seconds)


class BudgetIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.expected, self.contents, _, self.raw, self.head = fixture()

    def deadline(self, clock):
        return Deadline(0, 300, 300, 300, clock=clock)

    def model_files(self, directory):
        """Model permissions/fsync explicitly; this is not native FS evidence."""
        stack = ExitStack()
        stack.enter_context(
            patch.object(
                bridge.host, "private_directory", return_value=("model", "ACL")
            )
        )
        stack.enter_context(
            patch.object(bridge.host, "backup_recipient", return_value=RECIPIENT)
        )
        stack.enter_context(
            patch.object(
                bridge.host,
                "cipher_hash",
                side_effect=lambda path: bridge.sha(Path(path).read_bytes()),
            )
        )
        stack.enter_context(
            patch.object(
                bridge.stream,
                "private_file",
                side_effect=lambda path, **kw: Path(path).stat(),
            )
        )
        stack.enter_context(patch.object(bridge.os, "O_DIRECTORY", 0, create=True))
        original_open = os.open

        def opened(path, flags, *args, **kwargs):
            if Path(path) == Path(directory):
                return original_open(os.devnull, os.O_RDONLY)
            return original_open(path, flags, *args, **kwargs)

        stack.enter_context(patch.object(bridge.os, "open", side_effect=opened))
        stack.enter_context(patch.object(bridge.os, "fsync"))
        return stack

    def collect(self, directory, transport, deadline, callback=verifier):
        return bridge._collect(
            STAGE,
            directory,
            Path(directory) / "synthetic-identity",
            [RECIPIENT],
            self.expected,
            callback,
            transport=transport,
            deadline=deadline,
        )

    def test_expired_or_substitute_budget_denies_before_key_or_transport(self):
        clock = Clock()
        deadline = self.deadline(clock)
        clock.now = 180
        transport = TimedTransport(self.raw, self.head, clock)
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(bridge.host, "backup_recipient") as key,
        ):
            for invalid in (deadline, object(), True):
                with (
                    self.subTest(kind=type(invalid).__name__),
                    self.assertRaises(BudgetDenied),
                ):
                    self.collect(directory, transport, invalid)
        key.assert_not_called()
        self.assertEqual(transport.calls, [])

    def test_shared_capture_recovery_budget_shrinks_and_receipt_shapes_stay_equal(self):
        clock = Clock(100)
        deadline = self.deadline(clock)
        transport = TimedTransport(
            self.raw, self.head, clock, costs={"head": 2, "encrypt": 5, "decrypt": 5}
        )
        sql_caps = []

        def callback(dump, expected, seconds):
            sql_caps.append(seconds)
            clock.now += 5
            return verifier(dump, expected, seconds)

        with tempfile.TemporaryDirectory() as directory, self.model_files(directory):
            capture = self.collect(directory, transport, deadline, callback)
            ciphertext = Path(directory) / capture["encrypted_file"]
            recovery = bridge._verify_recovered(
                ciphertext,
                "synthetic-identity",
                self.expected,
                capture,
                callback,
                transport=transport,
                deadline=deadline,
            )
            # A separately modeled default call confirms no new receipt fields.
            default = self.collect(directory, FakeTransport(self.raw, self.head), None)
            default_recovery = bridge._verify_recovered(
                Path(directory) / default["encrypted_file"],
                "synthetic-identity",
                self.expected,
                default,
                verifier,
                transport=FakeTransport(self.raw, self.head),
            )
        self.assertEqual(
            transport.caps,
            [
                ("head", 20),
                ("encrypt", 70),
                ("decrypt", 69),
                ("head", 20),
                ("decrypt", 57),
            ],
        )
        self.assertEqual(sql_caps, [65, 53])
        self.assertEqual(deadline.end, 180)
        self.assertEqual(set(capture), set(default))
        self.assertEqual(set(recovery), set(default_recovery))
        self.assertEqual(capture["status"], recovery["status"])
        self.assertEqual(capture["status"], "modeled_only")

    def test_late_encrypt_removes_only_the_owned_pending_cipher(self):
        clock = Clock(170)
        deadline = self.deadline(clock)
        transport = TimedTransport(self.raw, self.head, clock, costs={"encrypt": 10})
        with tempfile.TemporaryDirectory() as directory, self.model_files(directory):
            keep = Path(directory) / "keep.age"
            keep.write_bytes(b"synthetic-sentinel")
            with self.assertRaises(BudgetDenied):
                self.collect(directory, transport, deadline)
            self.assertEqual(list(Path(directory).iterdir()), [keep])
        self.assertEqual(transport.calls, ["head", "encrypt"])

    def test_recovery_never_starts_a_fresh_120_second_sql_budget(self):
        clock = Clock(125)
        deadline = self.deadline(clock)
        transport = TimedTransport(self.raw, self.head, clock, costs={"decrypt": 8})
        capture = {
            "encrypted_sha256": "a" * 64,
            "plaintext_sha256": bridge.sha(self.raw),
        }
        with (
            patch.object(bridge.host, "cipher_hash", return_value="a" * 64),
            patch.object(bridge, "verify_ram", wraps=verification.verify_ram),
            patch(__name__ + ".verifier", wraps=verifier) as sql,
        ):
            with self.assertRaises(BudgetDenied):
                bridge._verify_recovered(
                    "synthetic-cipher",
                    "synthetic-identity",
                    self.expected,
                    capture,
                    verifier,
                    transport=transport,
                    deadline=deadline,
                )
        sql.assert_not_called()
        self.assertEqual(transport.caps, [("decrypt", 51)])

    def test_archive_elapsed_time_is_recomputed_before_exact_native_callback(self):
        clock = Clock()
        deadline = self.deadline(clock)
        original_read = verification.archive.read
        seen = []
        native = object.__new__(NativeSQLAdapter)

        def archive_read(*args):
            bundle = original_read(*args)
            clock.now = 100
            return bundle

        def native_call(instance, dump, expected, seconds):
            seen.append((instance, seconds, expected.verification_chain))
            return {
                **verifier(dump, expected, seconds),
                "mode": "actual_disposable_restore",
            }

        with (
            patch.object(verification.archive, "read", side_effect=archive_read),
            patch.object(NativeSQLAdapter, "__call__", native_call),
        ):
            result = verification.verify_ram(
                self.raw, self.expected, native, 120, deadline=deadline
            )
        self.assertEqual(seen, [(native, 77, self.contents["checkpoints.bin"])])
        self.assertEqual(result["sql_verifier_mode"], "actual_disposable_restore")
        # Patched native callback exercises admission/type only, not real SQL.

    def test_late_callback_result_is_denied_and_wrappers_cannot_claim_actual(self):
        for wrapped in (False, True):
            clock = Clock(100)
            deadline = self.deadline(clock)

            def callback(dump, expected, seconds):
                if not wrapped:
                    clock.now = 180
                return {
                    **verifier(dump, expected, seconds),
                    "mode": "actual_disposable_restore",
                }

            failure = bridge.stream.BackupError if wrapped else BudgetDenied
            category = (
                "actual_source_bound_adapter_required"
                if wrapped
                else "authority_session_expired"
            )
            with (
                self.subTest(wrapped=wrapped),
                self.assertRaisesRegex(failure, category),
            ):
                verification.verify_ram(
                    self.raw, self.expected, callback, 120, deadline=deadline
                )

    def test_subclass_cannot_replace_the_exact_native_adapter(self):
        class Substitute(NativeSQLAdapter):
            pass

        def native_call(instance, dump, expected, seconds):
            return {
                **verifier(dump, expected, seconds),
                "mode": "actual_disposable_restore",
            }

        with (
            patch.object(NativeSQLAdapter, "__call__", native_call),
            self.assertRaisesRegex(
                bridge.stream.BackupError, "actual_source_bound_adapter_required"
            ),
        ):
            verification.verify_ram(
                self.raw,
                self.expected,
                object.__new__(Substitute),
                120,
                deadline=self.deadline(Clock()),
            )

    def test_transport_uses_pinned_route_for_both_actions_and_clipped_metadata(self):
        route = ExporterRoute("a" * 64, "b" * 64)
        transport = bridge.Transport(route=route)
        with (
            patch.object(bridge.host, "ssh_command", side_effect=lambda args: args),
            patch.object(bridge.stream, "bounded_metadata", return_value=b"{}") as head,
            patch.object(bridge.stream, "encrypt_export", return_value={}) as encrypt,
        ):
            self.assertEqual(transport.head(STAGE, self.expected, seconds=7), {})
            transport.encrypt(
                STAGE, self.expected, [RECIPIENT], "synthetic-destination", 9
            )
        for call, action in ((head.call_args, "head"), (encrypt.call_args, "export")):
            argv = shlex.split(call.args[0][0])
            self.assertEqual(
                argv[:6], ["/usr/bin/python3", "-I", "-E", "-s", "-B", "-c"]
            )
            self.assertEqual(
                argv[-6:],
                [
                    STAGE,
                    route.helper_sha256,
                    route.manifest_sha256,
                    self.expected.exporter_sha256,
                    action,
                    self.expected.profile_sha256,
                ],
            )
        self.assertEqual(head.call_args.kwargs["seconds"], 7)
        self.assertEqual(encrypt.call_args.kwargs["seconds"], 9)

    def test_default_transport_preserves_legacy_primitive_call_shapes(self):
        transport = bridge.Transport()
        with (
            patch.object(
                bridge, "remote_command", return_value=["synthetic-command"]
            ) as command,
            patch.object(bridge.stream, "bounded_metadata", return_value=b"{}") as head,
            patch.object(bridge.stream, "encrypt_export", return_value={}) as encrypt,
        ):
            transport.head(STAGE, self.expected)
            transport.encrypt(
                STAGE, self.expected, [RECIPIENT], "synthetic-destination", 120
            )
        self.assertEqual(
            [call.args[1] for call in command.call_args_list], ["head", "export"]
        )
        self.assertTrue(all(not call.kwargs for call in command.call_args_list))
        self.assertEqual(head.call_args.args, (["synthetic-command"],))
        self.assertEqual(head.call_args.kwargs, {})
        self.assertEqual(
            encrypt.call_args.kwargs, {"seconds": 120, "maximum": bridge.MAX_ARCHIVE}
        )

    def test_invalid_route_cannot_invoke_ssh_or_claim_independent_review(self):
        with patch.object(bridge.host, "ssh_command") as ssh:
            for route in (
                object(),
                ExporterRoute(True, "b" * 64),
                ExporterRoute("a" * 64, "../manifest"),
            ):
                with (
                    self.subTest(kind=type(route).__name__),
                    self.assertRaises(bridge.stream.BackupError),
                ):
                    bridge.remote_command(STAGE, "head", self.expected, route=route)
        ssh.assert_not_called()


if __name__ == "__main__":
    unittest.main()
