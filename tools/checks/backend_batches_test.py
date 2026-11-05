"""Regression gates for complete batching, real pytest reports and cleanup."""

import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

import backend_batches as batches
from backend_test_support import inventory, xml


class InventoryTests(unittest.TestCase):
    def test_every_default_collected_case_is_in_one_stable_module_batch(self):
        cases = inventory()
        cases.append({**cases[0], "nodeid": "second", "name": "second"})
        plan = batches.plan(cases)
        self.assertEqual(len(plan), 4)
        self.assertEqual(
            sorted(case["nodeid"] for batch in plan for case in batch["cases"]),
            sorted(case["nodeid"] for case in cases),
        )
        self.assertEqual(plan, batches.plan(cases))
        self.assertEqual(len(plan[0]["cases"]), 3)
        for changed in (
            [],
            cases + [cases[0]],
            [{**cases[0], "module": "../foreign.py"}],
            [{**cases[0], "module": "/tests/foreign.py"}],
        ):
            with self.subTest(changed=changed), self.assertRaises(RuntimeError):
                batches.plan(changed)

    def test_real_default_pytest_collection_and_junit_include_both_file_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "tests").mkdir()
            (root / "pytest.ini").write_text("[pytest]\ntestpaths=tests\n")
            (root / "tests/test_alpha.py").write_text(
                "import pytest\n"
                "def test_capacity(): pass\n"
                "@pytest.mark.parametrize('value',[1,2],ids=['a::b','&[<>]'])\n"
                "def test_parameter(value): assert value\n"
            )
            (root / "tests/beta_test.py").write_text(
                "import unittest\n"
                "class TestBeta(unittest.TestCase):\n"
                " def test_subtests(self):\n"
                "  for x in range(3):\n"
                "   with self.subTest(x=x): self.assertGreaterEqual(x,0)\n"
            )
            environment = {
                "PATH": os.defpath,
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            command = [
                sys.executable,
                str(Path(batches.__file__).resolve()),
                "--collect=" + str(root / "inventory.json"),
                "--deselect=tests/test_alpha.py::test_capacity",
            ]
            result = subprocess.run(
                command, cwd=root, env=environment, capture_output=True, timeout=15
            )
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            plan = json.loads((root / "inventory.json").read_text())["batches"]
            self.assertEqual(sum(len(batch["cases"]) for batch in plan), 3)
            self.assertEqual(
                {module for batch in plan for module in batch["modules"]},
                {"tests/test_alpha.py", "tests/beta_test.py"},
            )
            for batch in plan:
                result = subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "pytest",
                        "-q",
                        "-p",
                        "no:cacheprovider",
                        "--deselect=tests/test_alpha.py::test_capacity",
                        "--junitxml=" + str(root / f"bank-batch-{batch['id']}.xml"),
                        *batch["modules"],
                    ],
                    cwd=root,
                    env=environment,
                    capture_output=True,
                    timeout=15,
                )
                self.assertEqual(result.returncode, 0, result.stdout.decode())
            self.assertEqual(batches.merge(root, "bank", plan)["unique_tests"], 3)
            command[-1] = "--deselect=tests/test_alpha.py::missing"
            result = subprocess.run(
                command, cwd=root, env=environment, capture_output=True, timeout=15
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b"deselection_not_exact", result.stderr)

    def test_exact_junit_union_accepts_passed_subtest_counts_without_inflation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            plan = batches.plan(inventory())
            for batch in plan:
                (root / f"bank-batch-{batch['id']}.xml").write_bytes(
                    xml(batch["cases"], extra_passed_subtests=3)
                )
            result = batches.merge(root, "bank", plan)
            self.assertEqual(result, {"batches": 4, "unique_tests": 8})
            self.assertEqual(len(list(ET.parse(root / "bank.xml").iter("testcase"))), 8)

    def test_missing_duplicate_foreign_overlap_and_false_junit_counts_fail(self):
        for mutation in (
            "missing",
            "duplicate",
            "foreign",
            "overlap",
            "count",
            "status",
        ):
            with (
                self.subTest(mutation=mutation),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory)
                plan = batches.plan(inventory())
                changed = copy.deepcopy(plan[0]["cases"])
                if mutation == "missing":
                    changed.pop()
                elif mutation == "duplicate":
                    changed.append(changed[0])
                elif mutation == "foreign":
                    changed[0]["name"] = "foreign"
                elif mutation == "overlap":
                    plan[1]["cases"].append(plan[0]["cases"][0])
                for batch in plan:
                    document = ET.fromstring(
                        xml(changed if batch["id"] == "01" else batch["cases"])
                    )
                    if batch["id"] == "01" and mutation in {"count", "status"}:
                        document[0].set(
                            "tests" if mutation == "count" else "failures",
                            "0" if mutation == "count" else "1",
                        )
                    (root / f"bank-batch-{batch['id']}.xml").write_bytes(
                        ET.tostring(document)
                    )
                with self.assertRaises(RuntimeError):
                    batches.merge(root, "bank", plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
