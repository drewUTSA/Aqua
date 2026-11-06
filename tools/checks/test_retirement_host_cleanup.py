"""Daemon-response fault regressions; no Docker or private inputs are used."""

from contextlib import ExitStack, redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import retirement_host_setup as setup
import run_retirement_host as runner


class FlagCleanupTests(unittest.TestCase):
    def test_lost_create_layout_start_and_inspect_responses_remove_owned_clear(self):
        for fault in ("create", "layout", "start", "inspect"):

            class Owned:
                attempted = []
                owned = False
                removals = 0
                append_ready = True

                def create(self, operation):
                    self.attempted = [operation]
                    self.owned = True
                    if fault == "create":
                        raise RuntimeError("injected_create_reply_loss")
                    return "f" * 64

                def verify_layout(self):
                    if fault == "layout":
                        raise RuntimeError("injected_layout_replacement")

                def timeout(self, maximum):
                    return maximum

                def remove(self, operation):
                    assert operation == "clear"
                    self.removals += 1
                    self.owned = False
                    return True

            def docker(*args, **kwargs):
                if args[0] == fault:
                    raise RuntimeError("injected_" + fault + "_reply_loss")
                return b"false 0\n"

            owned = Owned()
            with (
                self.subTest(fault=fault),
                patch.object(setup.commands, "docker", side_effect=docker),
            ):
                with self.assertRaises(RuntimeError):
                    setup.flag(owned, "clear")
                self.assertEqual(owned.removals, 1)
                self.assertFalse(owned.owned)
                self.assertFalse(
                    owned.append_ready
                )  # Cleanup keeps signer admission closed even on an uncertain flag.

    def controller(self, uncertain):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw).resolve()

            class Owned:
                attempted = ["pg", "set"]
                volume_attempted = False
                owned_clear = False
                clear_removals = 0
                append_ready = True

                def __init__(self):
                    self.root = root / "owned"
                    (self.root / "authority").mkdir(parents=True)
                    for name in ("checkpoints.bin", "poison.bin"):
                        (self.root / "authority" / name).write_bytes(
                            b"public fixture bytes"
                        )
                    self.attempted = ["pg", "set"]

                def create(self, operation):
                    assert operation == "clear"
                    self.attempted.append(operation)
                    self.owned_clear = True
                    return "f" * 64

                def verify_layout(self):
                    pass

                def timeout(self, maximum):
                    return maximum

                def remove(self, operation):
                    if operation != "clear":
                        return True
                    self.clear_removals += 1
                    if uncertain:
                        return False
                    if self.clear_removals == 1:
                        raise RuntimeError("injected_first_remove_reply_loss")
                    self.owned_clear = False
                    return True

            owned = Owned()
            image = "sha256:" + "a" * 64
            source = b"public synthetic source"

            def docker(*args, **kwargs):
                if args[:2] == ("image", "inspect"):
                    return image.encode()
                assert args[:2] == ("start", "--attach")
                raise RuntimeError("injected_clear_start_reply_loss")

            with ExitStack() as stack:
                for target, name, value in (
                    (runner, "BASE", root),
                    (runner.sys, "platform", "linux"),
                    (runner, "Resources", lambda *args: owned),
                    (runner, "source", lambda: source),
                    (runner, "running", lambda: []),
                    (runner, "states", lambda ids: []),
                    (runner, "directories", lambda *args: None),
                    (runner.os, "geteuid", lambda: 1000),
                ):
                    stack.enter_context(patch.object(target, name, value))
                stack.enter_context(
                    patch.object(
                        runner,
                        "database",
                        side_effect=RuntimeError("injected_work_failure"),
                    )
                )
                stack.enter_context(
                    patch.object(runner.commands, "docker", side_effect=docker)
                )
                stack.enter_context(redirect_stdout(io.StringIO()))
                code = runner.execute(
                    image,
                    hashlib.sha256(source).hexdigest(),
                    "aqua-retirement-host-" + "a" * 24,
                )
            report = json.loads((owned.root / "report.json").read_text())
            self.assertEqual(code, 1)
            self.assertFalse(report["cleanup"])
            self.assertFalse(report["append_flags_cleared"])
            self.assertIn("append_flag_cleanup", report["remaining_resources"])
            return owned, report

    def test_outer_second_sweep_removes_clear_created_after_initial_sweep(self):
        owned, report = self.controller(uncertain=False)
        self.assertEqual(owned.clear_removals, 2)
        self.assertFalse(owned.owned_clear)
        self.assertNotIn("clear", report["remaining_resources"])

    def test_unconfirmed_clear_container_remains_explicit_and_never_green(self):
        owned, report = self.controller(uncertain=True)
        self.assertEqual(owned.clear_removals, 2)
        self.assertTrue(owned.owned_clear)
        self.assertIn("clear", report["remaining_resources"])


if __name__ == "__main__":
    unittest.main()
