"""Offline negative checks for the capability-bearing disposable executor."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import retirement_durability_resources as resources
import run_retirement_durability as runner


class DurabilityGuards(unittest.TestCase):
    def test_default_is_source_bound_without_docker_or_writes(self):
        completed = subprocess.run(
            [sys.executable, str(Path(runner.__file__).resolve())],
            capture_output=True,
            timeout=5,
            check=True,
        )
        report = json.loads(completed.stdout)
        self.assertEqual(report["status"], "prepared_only")
        self.assertEqual((report["Docker_actions"], report["writes"]), (0, 0))
        self.assertEqual(report["source_sha256"], resources.source()[1])
        self.assertEqual(report["signer_capabilities"], [])
        self.assertTrue(report["native_execution_held_until_coordinator_release"])

    def test_exact_image_and_source_pins_required_before_any_host_action(self):
        for image, expected in (
            ("aqua-checks:latest", "a" * 64),
            ("sha256:" + "a" * 64, "PENDING"),
            ("sha256:" + "a" * 64 + ";evil", "b" * 64),
        ):
            with self.subTest(image=image, expected=expected):
                with patch.object(runner, "validate_base") as host:
                    with patch.object(runner.commands, "docker") as docker:
                        with self.assertRaises(RuntimeError):
                            runner.execute(image, expected)
                host.assert_not_called()
                docker.assert_not_called()

    def test_changed_source_denied_before_docker_or_directory_creation(self):
        with patch.object(runner, "validate_base"):
            with patch.object(runner.commands, "docker") as docker:
                with self.assertRaisesRegex(RuntimeError, "source_changed"):
                    runner.execute(
                        "sha256:" + "a" * 64, "0" * 64, "p11bc-durability-" + "3" * 24
                    )
        docker.assert_not_called()

    def test_only_three_exact_roles_and_current_fresh_qa_tree_are_allowed(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            run = "p11bc-durability-" + "1" * 24
            directory = base / run
            directory.mkdir()
            (directory / "authority").mkdir()
            with patch.object(resources, "BASE", base):
                fixture = resources.Resources(
                    run, "sha256:" + "a" * 64, directory, b"# frozen public setter"
                )
                for role in ("production", "../set", "set;evil", "-pg"):
                    with self.assertRaises(ValueError):
                        fixture.create(role)
                with self.assertRaises(ValueError):
                    resources.Resources(
                        run, "aqua-checks:latest", directory, b"# frozen public setter"
                    )
                with self.assertRaises(ValueError):
                    resources.Resources(
                        run, "sha256:" + "a" * 64, base, b"# frozen public setter"
                    )

    def test_privileges_and_mounts_are_scoped_to_fixture_and_never_docker_socket(self):
        with tempfile.TemporaryDirectory() as raw:
            base = Path(raw).resolve()
            run = "p11bc-durability-" + "2" * 24
            directory = base / run
            directory.mkdir()
            (directory / "authority").mkdir()
            with patch.object(resources, "BASE", base):
                fixture = resources.Resources(
                    run, "sha256:" + "a" * 64, directory, b"# frozen public setter"
                )
                for role in ("initialize", "probe", "set", "clear"):
                    with patch.object(fixture, "identifier", return_value="f" * 64):
                        with patch.object(
                            resources.commands,
                            "docker",
                            return_value=("f" * 64).encode(),
                        ) as docker:
                            fixture.create(role)
                    arguments = docker.call_args.args
                    self.assertIn("--network=none", arguments)
                    self.assertIn("--read-only", arguments)
                    self.assertIn("--cap-drop=ALL", arguments)
                    self.assertIn("--security-opt=no-new-privileges:true", arguments)
                    caps = [arg for arg in arguments if arg.startswith("--cap-add=")]
                    self.assertEqual(
                        caps,
                        (
                            []
                            if role in {"initialize", "probe"}
                            else [
                                "--cap-add=LINUX_IMMUTABLE",
                                "--cap-add=FOWNER",
                                "--cap-add=DAC_OVERRIDE",
                            ]
                        ),
                    )
                    mounts = [arg for arg in arguments if arg.startswith("--mount=")]
                    self.assertEqual(
                        len(mounts), 2 if role in {"initialize", "probe"} else 1
                    )
                    self.assertTrue(
                        all("src=" + str(directory) + "/" in arg for arg in mounts)
                    )
                    self.assertNotIn("docker.sock", " ".join(mounts))
                    if role not in {"initialize", "probe"}:
                        self.assertIn("# frozen public setter", arguments)
                        self.assertTrue(
                            any(
                                arg.startswith("--env=AQUA_FIXTURE_INODE=")
                                for arg in arguments
                            )
                        )
                with self.assertRaises(ValueError):
                    fixture.create("set")

    def test_source_fingerprint_covers_probe_setter_executor_and_actual_verifier(self):
        contents, digest = resources.source()
        self.assertEqual(len(digest), 64)
        for relative in (
            "backend/retirement/checkpoint.py",
            "backend/retirement/publisher.py",
            "tools/checks/retirement_fixture/kernel_probe.py",
            "tools/checks/retirement_fixture/append_flags.py",
            "tools/checks/run_retirement_durability.py",
            "tools/checks/retirement_durability_resources.py",
            "tools/checks/p05_browser_docker.py",
            "ops/retirement/initialize.py",
        ):
            self.assertIn(relative, contents)
        self.assertFalse(any(".env" in name or "private" in name for name in contents))


if __name__ == "__main__":
    unittest.main()
