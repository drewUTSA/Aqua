"""Transient proc visibility must not relax exact process identity or its budget."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

SOURCE = Path(__file__).resolve().parent / "retirement_fixture/normal_runtime_probe.py"
spec = importlib.util.spec_from_file_location("normal_argv_probe", SOURCE)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class ArgvVisibility(unittest.TestCase):
    def check(self, values, *, children="", times=(1, 2), exit_code=None):
        node = SimpleNamespace(
            read_bytes=Mock(side_effect=values), read_text=lambda: children
        )
        child = SimpleNamespace(pid=12345, poll=lambda: exit_code)
        with (
            patch.object(probe, "Path", return_value=node),
            patch.object(probe.time, "monotonic", side_effect=times),
            patch.object(probe.time, "sleep") as sleep,
        ):
            self.observed = (node, sleep)
            probe.single_ordinary_uvicorn(child, 10)
        return node, sleep

    def test_empty_then_exact_exec_is_observed_without_a_second_launch(self):
        exact = b"\0".join(value.encode() for value in probe.ARGV) + b"\0"
        node, sleep = self.check([b"", exact])
        self.assertEqual(node.read_bytes.call_count, 2)
        sleep.assert_called_once_with(0.005)

    def test_nonempty_wrong_command_and_descendants_are_never_retried(self):
        exact = b"\0".join(value.encode() for value in probe.ARGV) + b"\0"
        for values, children in [
            ([b"wrong-command\0", exact], ""),
            ([b"wrong-command", exact], ""),
            ([b"\0", exact], ""),
            ([exact], "54321"),
        ]:
            with (
                self.subTest(children=bool(children)),
                self.assertRaisesRegex(RuntimeError, "not_single_ordinary_uvicorn"),
            ):
                self.check(values, children=children)
            node, sleep = self.observed
            self.assertEqual(node.read_bytes.call_count, 1)
            sleep.assert_not_called()

    def test_empty_identity_must_resolve_inside_the_original_deadline(self):
        with self.assertRaisesRegex(RuntimeError, "not_single_ordinary_uvicorn"):
            self.check([b"", b""], times=(1, 9, 10))

    def test_exited_child_and_expired_budget_cannot_claim_identity(self):
        for values, times, exit_code in [([], (1,), 0), ([], (10,), None)]:
            with (
                self.subTest(exit=exit_code),
                self.assertRaisesRegex(RuntimeError, "not_single_ordinary_uvicorn"),
            ):
                self.check(values, times=times, exit_code=exit_code)


if __name__ == "__main__":
    unittest.main()
