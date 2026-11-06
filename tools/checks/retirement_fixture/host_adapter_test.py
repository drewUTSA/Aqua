"""Host adapter guards with fake config and ephemeral in-memory keys only."""

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

HERE = Path(__file__).parent
spec = importlib.util.spec_from_file_location(
    "private_retirement_host",
    HERE.resolve().parents[2] / "ops/retirement/retirement_host.py",
)
host = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = host
spec.loader.exec_module(host)


def config():
    return {
        "installation_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "identity_key_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "key_commitment": "a" * 64,
        "public_key": "b" * 64,
        "checkpoint_dsn": "postgresql://aqua_retirement_checkpoint:"
        + "s" * 43
        + "@/aqua_retirement?host=/run/aqua-app-db&port=5432&sslmode=disable",
    }


class HostAdapterTests(unittest.TestCase):
    def test_default_process_reads_no_private_config_key_or_pool(self):
        result = subprocess.run(
            [
                sys.executable,
                "-E",
                "-s",
                "-B",
                str(HERE.resolve().parents[2] / "ops/retirement/retirement_host.py"),
            ],
            capture_output=True,
            timeout=3,
            check=True,
        )
        self.assertEqual(
            json.loads(result.stdout),
            {
                "status": "prepared_only",
                "key_reads": 0,
                "pool_opens": 0,
                "max_seconds": 55,
                "max_steps": 55,
            },
        )

    def test_config_is_closed_socket_role_only_and_password_repr_hidden(self):
        value = host.parse_settings(json.dumps(config()).encode())
        self.assertNotIn("s" * 43, repr(value))
        self.assertEqual(value.installation, config()["installation_id"])
        for changed in (
            {**config(), "extra": "value"},
            {**config(), "public_key": "B" * 64},
            {
                **config(),
                "checkpoint_dsn": config()["checkpoint_dsn"].replace(
                    "aqua_retirement_checkpoint", "aqua_app_runtime"
                ),
            },
            {
                **config(),
                "checkpoint_dsn": config()["checkpoint_dsn"] + "&service=alternate",
            },
            {
                **config(),
                "checkpoint_dsn": config()["checkpoint_dsn"].replace(
                    "/run/aqua-app-db", "127.0.0.1"
                ),
            },
        ):
            with self.assertRaises(host.HostUnavailable):
                host.parse_settings(json.dumps(changed).encode())
        raw = json.dumps(config())[:-1] + ',"public_key":"' + "c" * 64 + '"}'
        with self.assertRaises(host.HostUnavailable):
            host.parse_settings(raw.encode())

    def test_wrong_signing_key_cannot_open_a_pool_or_touch_checkpoint(self):
        private = Ed25519PrivateKey.generate()
        seed = private.private_bytes_raw()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        with patch.object(host, "read_private", return_value=seed):
            self.assertIsNotNone(host.signing_key(Path("/synthetic/key"), public))
            with self.assertRaises(host.HostUnavailable):
                host.signing_key(Path("/synthetic/key"), bytes(32))

    def test_loop_obeys_step_count_wall_deadline_and_one_second_cadence(self):
        now = [0.0]
        calls = []

        def once():
            calls.append(now[0])
            now[0] += 0.1
            return object()

        def sleep(seconds):
            self.assertGreater(seconds, 0)
            self.assertLessEqual(seconds, 1)
            now[0] += seconds

        value = host.tick_loop(
            SimpleNamespace(once=once), deadline=55.0, clock=lambda: now[0], sleep=sleep
        )
        self.assertEqual(value, {"status": "checked", "steps": 55})
        self.assertLessEqual(now[0], 55.0)
        for left, right in zip(calls, calls[1:]):
            self.assertAlmostEqual(right - left, 1.0)

    def test_failure_and_invalid_deadline_never_report_success_or_extend_budget(self):
        calls = []

        def fail():
            calls.append(1)
            raise host.HostUnavailable()

        with self.assertRaises(host.HostUnavailable):
            host.tick_loop(SimpleNamespace(once=fail), deadline=55.0, clock=lambda: 0.0)
        self.assertEqual(calls, [1])
        for deadline in (None, True, float("nan"), float("inf"), 56, -1):
            with self.assertRaises(host.HostUnavailable):
                host.tick_loop(
                    SimpleNamespace(once=lambda: self.fail("bad budget admitted")),
                    deadline=deadline,
                    clock=lambda: 0.0,
                )

    @unittest.skipUnless(os.name == "posix", "actual Linux FD/UID/mode guard")
    def test_private_file_checks_real_owner_modes_link_size_before_key_read(self):
        self.assertEqual(os.geteuid(), 1000)
        with tempfile.TemporaryDirectory(prefix=".host-native-", dir=HERE) as name:
            root = Path(name).resolve()
            self.assertEqual(root.parent, HERE.resolve())
            root.chmod(0o700)
            path = root / "synthetic.key"
            path.write_bytes(b"s" * 32)
            path.chmod(0o600)
            self.assertEqual(host.read_private(path, 32, exact=32), b"s" * 32)
            path.chmod(0o640)
            with self.assertRaises(host.HostUnavailable):
                host.read_private(path, 32, exact=32)
            path.chmod(0o600)
            alias = root / "alias"
            os.link(path, alias)
            with self.assertRaises(host.HostUnavailable):
                host.read_private(path, 32, exact=32)
            alias.unlink()
            path.write_bytes(b"s" * 33)
            with self.assertRaises(host.HostUnavailable):
                host.read_private(path, 32, exact=32)


if __name__ == "__main__":
    unittest.main()
