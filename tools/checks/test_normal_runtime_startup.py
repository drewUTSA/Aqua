"""Expected ASGI admission failure is actual closed exit, never invented503."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

path = Path(__file__).resolve().parent / "retirement_fixture/normal_runtime_probe.py"
spec = importlib.util.spec_from_file_location("normal_startup_exit_probe", path)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class StartupExitGuards(unittest.TestCase):
    diagnostic = b"Traceback: bounded fixture\nretirement.interlock.RetirementUnavailable: retirement_authority_unavailable\n"

    def child(self, code=3):
        return SimpleNamespace(pid=2147483647, wait=lambda timeout: code)

    def test_closed_exit_requires_nonzero_reaped_PID_no_listener_no_private_response(
        self,
    ):
        socket = SimpleNamespace(
            settimeout=lambda value: None,
            connect_ex=lambda address: 111,
            close=lambda: None,
        )
        with (
            patch.object(probe.socket, "socket", return_value=socket),
            patch.object(
                probe, "request", side_effect=OSError("not listening")
            ) as requests,
        ):
            result = probe.closed_startup(
                self.child(), "a" * 64, (1, 2, 3, 4), self.diagnostic
            )
        self.assertEqual(result["startup_mode"], "startup_exited_closed")
        self.assertEqual(result["actual_child_exit_code"], 3)
        self.assertIs(result["private_api_admitted"], False)
        self.assertEqual(result["web_processes"], 0)
        self.assertEqual(requests.call_count, 2)
        self.assertNotIn("503", str(result))
        self.assertEqual(result["failure_category"], "retirement_authority_unavailable")
        self.assertEqual(len(result["stderr_sha256"]), 64)
        self.assertNotIn("Traceback", str(result))

    def test_zero_exit_or_surviving_listener_is_not_a_valid_restore_denial(self):
        with self.assertRaises(RuntimeError):
            probe.closed_startup(self.child(0), "a" * 64, (1, 2, 3, 4), self.diagnostic)
        socket = SimpleNamespace(
            settimeout=lambda value: None,
            connect_ex=lambda address: 0,
            close=lambda: None,
        )
        with (
            patch.object(probe.socket, "socket", return_value=socket),
            patch.object(probe, "request") as requests,
        ):
            with self.assertRaises(RuntimeError):
                probe.closed_startup(
                    self.child(), "a" * 64, (1, 2, 3, 4), self.diagnostic
                )
            requests.assert_not_called()

    def test_any_admitted_private_response_stays_red(self):
        socket = SimpleNamespace(
            settimeout=lambda value: None,
            connect_ex=lambda address: 111,
            close=lambda: None,
        )
        with (
            patch.object(probe.socket, "socket", return_value=socket),
            patch.object(probe, "request", return_value=(200, {}, {})),
        ):
            with self.assertRaises(RuntimeError):
                probe.closed_startup(
                    self.child(), "a" * 64, (1, 2, 3, 4), self.diagnostic
                )

    def test_import_config_unknown_and_oversized_stderr_cannot_count_as_restore_denial(
        self,
    ):
        for raw in (
            b"ImportError: broken source\n",
            b"ConfigError: missing settings\n",
            b"RetirementUnavailable: unrelated\n",
            b"x" * 16385,
        ):
            with self.subTest(raw=raw[:40]), self.assertRaises(RuntimeError):
                probe.closed_startup(self.child(), "a" * 64, (1, 2, 3, 4), raw)

    def test_closed_path_keeps_both_physical_inode_identity_checks(self):
        node = SimpleNamespace(stat=lambda: SimpleNamespace(st_dev=1, st_ino=2))
        with patch.object(probe, "Path", return_value=node):
            probe.same_inodes((1, 2, 1, 2))
            with self.assertRaises(RuntimeError):
                probe.same_inodes((1, 2, 1, 3))


if __name__ == "__main__":
    unittest.main()
