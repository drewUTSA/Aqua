"""Verify sequential ownership and fail-closed deadlines for backend batches."""

import json
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import backend_batches as batches
import privacy_capacity_fixture as capacity
import run_backend
from backend_test_support import inventory, xml


class ExecutionTests(unittest.TestCase):
    def exercise(self, timeout=False):
        active, provisions, commands = set(), [], []
        plan = batches.plan(inventory())

        def provision(image, name, owned, archive):
            self.assertFalse(active, "next pair started before absence confirmed")
            self.assertEqual(archive, b"one frozen source archive")
            provisions.append(name)
            pair = (name + "-pg", name + "-tests")
            owned.extend(pair)
            active.update(pair)
            return pair

        def docker(*args, **kwargs):
            if args[0] == "rm":
                active.remove(args[-1])
            if args[:2] == ("image", "inspect"):
                return b"sha256:fixed-image"
            if args[-1] == "/tmp/collection.json":
                return json.dumps({"schema": 1, "batches": plan}).encode()
            if args[-1] == "/tmp/batch.xml":
                selected = int(args[1].split("-")[-2]) - 1
                return xml(plan[selected]["cases"], extra_passed_subtests=2)
            if "freeze" in args:
                return b"one frozen package set"
            if "df" in args:
                return (
                    b"Filesystem Size Used Avail Use%\ntmpfs 524288 128000 396288 25%\n"
                )
            return b""

        def process(command, **kwargs):
            if command[:3] == ["docker", "container", "inspect"]:
                return SimpleNamespace(returncode=1, stderr=b"No such container")
            if "pytest" in command:
                commands.append(command)
                self.assertEqual(kwargs["timeout"], 120)
                self.assertEqual(
                    command.count("--deselect=" + capacity.CAPACITY_CASE), 1
                )
                if timeout:
                    raise subprocess.TimeoutExpired(
                        command, 120, output=b"last test progress", stderr=b"deadline"
                    )
            else:
                self.assertEqual(kwargs["timeout"], 60)
            return SimpleNamespace(returncode=0, stdout=b"passed", stderr=b"")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch.object(run_backend, "provision_core", side_effect=provision),
                patch.object(run_backend, "docker", side_effect=docker),
                patch.object(run_backend.subprocess, "run", side_effect=process),
                patch.object(
                    run_backend, "verify_restore", return_value={"status": "passed"}
                ),
                patch.object(
                    run_backend,
                    "source_archive",
                    return_value=b"one frozen source archive",
                ),
                patch.object(run_backend, "coverage", return_value={"unique_tests": 9}),
                patch.object(
                    capacity, "verify", return_value={"status": "passed"}
                ) as fresh,
                patch("builtins.print"),
            ):
                code = run_backend.run("fixed-image", root)
            report = json.loads((root / "report.json").read_text())
            if timeout:
                self.assertEqual(
                    (root / "bank-batch-01.txt").read_bytes(),
                    b"last test progressdeadline",
                )
            else:
                self.assertEqual(
                    len(list(ET.parse(root / "bank.xml").iter("testcase"))), 8
                )
        self.assertFalse(active)
        return code, report, provisions, commands, fresh.call_count

    def test_all_four_batches_each_dataset_restore_and_cleanup_before_capacity(self):
        code, report, provisions, commands, fresh = self.exercise()
        self.assertEqual(code, 0, report)
        self.assertEqual(len(provisions), 8)
        self.assertEqual(len(commands), 8)
        self.assertEqual(fresh, 1)
        self.assertTrue(
            all(
                row["cleanup"] == "removed_and_absence_confirmed"
                for row in report["core_batches"]
            )
        )
        self.assertEqual([row["unique_tests"] for row in report["results"]], [8, 8])

    def test_timeout_retains_progress_and_stops_before_any_other_pair_or_capacity(self):
        code, report, provisions, commands, fresh = self.exercise(timeout=True)
        self.assertEqual(code, 1)
        self.assertEqual(len(provisions), 1)
        self.assertEqual(len(commands), 1)
        self.assertEqual(fresh, 0)
        self.assertIn("bank-batch-01", report["error"])
        self.assertEqual(report["cleanup"], "removed_and_absence_confirmed")
        self.assertEqual(report["core_batches"][0]["status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
