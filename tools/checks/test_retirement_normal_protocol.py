"""Pure actual-pipe red/green framing boundaries; no PG/Docker/native claims."""

from contextlib import contextmanager
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
EXPORT_SPEC = importlib.util.spec_from_file_location(
    "ops.retirement.export_protocol",
    ROOT.parents[1] / "ops/retirement/export_protocol.py",
)
EXPORT = importlib.util.module_from_spec(EXPORT_SPEC)
EXPORT_SPEC.loader.exec_module(EXPORT)
sys.modules["ops.retirement.export_protocol"] = EXPORT
SPEC = importlib.util.spec_from_file_location(
    "normal_protocol", ROOT / "retirement_normal_protocol.py"
)
PROTOCOL = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROTOCOL)


@contextmanager
def process(raw=b""):
    read_out, write_out = os.pipe()
    read_in, write_in = os.pipe()
    os.write(write_out, raw)
    os.close(write_out)
    value = SimpleNamespace(
        stdout=os.fdopen(read_out, "rb", buffering=0),
        stdin=os.fdopen(write_in, "wb", buffering=0),
    )
    try:
        yield value
    finally:
        value.stdout.close()
        value.stdin.close()
        os.close(read_in)


class Framing(unittest.TestCase):
    def test_old128_rejects_known_pool_style_line_new_seed_keeps_private_frame(self):
        # Source-known psycopg.pool format, deliberately synthetic; actual red
        # offending bytes were not retained, so this is not an attribution claim.
        diagnostic = (
            b"error connecting in 'pool-1': connection failed on synthetic fixture socket: "
            + b"bounded diagnostic detail " * 5
        )
        private_prefix = b"NEVER_LOG_PRIVATE\nNATIVE_MISSPELLED\n"
        private = private_prefix + b"S" * (8192 - len(private_prefix))
        raw = diagnostic + b"\nREADY_FOR_BACKUP\nNORMAL_RECEIPT 8192\n" + private
        with process(diagnostic + b"\n") as child:
            with self.assertRaisesRegex(
                RuntimeError, "retirement_export_header_capacity"
            ):
                PROTOCOL.Channel(child, time.monotonic() + 1).line()
        with process(raw) as child:
            channel = PROTOCOL.SeedChannel(child, time.monotonic() + 1)
            channel.diagnostic(channel.next_line())
            self.assertEqual(channel.next_line(), b"READY_FOR_BACKUP")
            self.assertEqual(channel.next_line(), b"NORMAL_RECEIPT 8192")
            from io import BytesIO

            sink = BytesIO()
            channel.exact(8192, sink)
            self.assertEqual(sink.getvalue(), private)
            self.assertEqual(channel.pending, b"")
            self.assertEqual(channel.receive(), b"")
            safe = channel.public_diagnostics()
            self.assertEqual(safe["diagnostic_lines"], 1)
            self.assertEqual(safe["last_category"], "pool_connection_diagnostic")
            self.assertNotIn(diagnostic.decode(), json.dumps(safe))
            self.assertNotIn(private.decode(), json.dumps(safe))
            self.assertNotIn("NEVER_LOG_PRIVATE", json.dumps(safe))

    def test_fixed_recovery_public_keys_exceed128_and_body_remains_framed(self):
        value = {
            "status": "passed",
            "offline_recovery": {},
            "new_UUID_distinct": True,
            "new_UUID_legacy_grants": 0,
            "setup_actor_normal_factory_claimed": False,
        }
        public = json.dumps(value, sort_keys=True).encode()
        self.assertGreater(len(public), 128)
        with process(public + b"\n") as child:
            with self.assertRaisesRegex(
                RuntimeError, "retirement_export_header_capacity"
            ):
                PROTOCOL.Channel(child, time.monotonic() + 1).line()
        raw = public + b"\nNORMAL_REPAIRED 7\nprivate"
        with process(raw) as child:
            channel = PROTOCOL.Channel(child, time.monotonic() + 1)
            self.assertEqual(json.loads(PROTOCOL.bounded_line(channel, 16384)), value)
            self.assertEqual(channel.line(), b"NORMAL_REPAIRED 7")
            from io import BytesIO

            sink = BytesIO()
            channel.exact(7, sink)
            self.assertEqual(sink.getvalue(), b"private")
            self.assertEqual(channel.pending, b"")
            self.assertEqual(channel.receive(), b"")

    def test_public_json_over16KiB_is_rejected(self):
        channel = SimpleNamespace(pending=bytearray(b"x" * 16385 + b"\n"))
        with self.assertRaisesRegex(
            RuntimeError, "normal_fixture_public_line_capacity"
        ):
            PROTOCOL.bounded_line(channel, 16384)

    def test_control_header128_is_preserved(self):
        with process(b"NORMAL_RECEIPT " + b"9" * 129 + b"\n") as child:
            with self.assertRaisesRegex(
                RuntimeError, "retirement_export_header_capacity"
            ):
                PROTOCOL.SeedChannel(child, time.monotonic() + 1).next_line()

    def test_seed_total1MiB_includes_private_reads(self):
        with process() as child:
            channel = PROTOCOL.SeedChannel(child, time.monotonic() + 1)
            with patch.object(PROTOCOL.Channel, "receive", return_value=b"x" * 65536):
                for _ in range(16):
                    self.assertEqual(len(channel.receive()), 65536)
                with self.assertRaisesRegex(
                    RuntimeError, "native_fixture_output_capacity"
                ):
                    channel.receive()

    def test_unknown_control_traceback_and_wrong_mode_json_fail_closed(self):
        for line, category in (
            (b"NATIVE_MISSPELLED", "unknown_control"),
            (b"Traceback (most recent call last):", "child_traceback"),
            (b'{"status":"passed"}', "unexpected_public_result"),
        ):
            with self.subTest(category=category), process() as child:
                channel = PROTOCOL.SeedChannel(child, time.monotonic() + 1)
                with self.assertRaises(RuntimeError):
                    channel.diagnostic(line)
                self.assertEqual(
                    channel.public_diagnostics()["last_category"], category
                )


if __name__ == "__main__":
    unittest.main()
