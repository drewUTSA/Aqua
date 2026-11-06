"""Pure closed-collection/model adapter guards; no signal-suite replay or Docker."""

import ast
import copy
import hashlib
import json
from pathlib import Path
import unittest
from types import SimpleNamespace

import run_retirement_native as native
import run_retirement_signals as signals


def passed():
    return {
        "tests": 48,
        "passed": 48,
        "failed": 0,
        "source_sha256": "a" * 64,
        "launcher_sha256": signals.LAUNCHER_SHA,
        "child_runner_sha256": signals.CHILD_SHA,
        "external_posix_delivery": {"status": "passed", "count": 6},
        "focused_baseline": False,
        "child_timeout_seconds": 10,
        "native_Docker_private_files_services_network": False,
        "actual_Docker_clean_exercised": True,
        "native_cleanup_guaranteed": False,
        "outcomes": [
            {
                "case": case,
                "passed": True,
                "child": {
                    "case": case,
                    "handlers_restored": True,
                    "active_guard_released": True,
                    "sentinel_exposed": False,
                },
            }
            for case in signals.EXPECTED
        ],
    }


class ClosedSignals(unittest.TestCase):
    def test_failed_child_projection_never_retains_raw_output_or_dynamic_messages(self):
        value = passed()
        value["outcomes"][0].update(
            passed=False,
            failure_category="PRIVATE_TEXT_SENTINEL",
            child_stdout="PRIVATE_CHILD_SENTINEL",
        )
        result = SimpleNamespace(
            returncode=1, stdout=json.dumps(value).encode(), stderr=b"PRIVATE_STDERR"
        )
        diagnostic = signals.public_diagnostic(result, "a" * 64)
        self.assertEqual(
            diagnostic["failed_cases"],
            [{"case": "prepared", "category": "unclassified"}],
        )
        self.assertNotIn("PRIVATE", json.dumps(diagnostic))
        log = json.dumps({"publisher_signal_diagnostic": diagnostic}).encode()
        self.assertEqual(native.signal_diagnostic(log), diagnostic)

    def test_diagnostic_rejects_private_fields_unknown_cases_and_boolean_counts(self):
        result = SimpleNamespace(
            returncode=0, stdout=json.dumps(passed()).encode(), stderr=b""
        )
        original = signals.public_diagnostic(result, "a" * 64)
        variants = []
        value = copy.deepcopy(original)
        value["stderr"] = "PRIVATE"
        variants.append(value)
        value = copy.deepcopy(original)
        value["failed_cases"] = [{"case": "PRIVATE", "category": "AssertionError"}]
        variants.append(value)
        value = copy.deepcopy(original)
        value["reported_tests"] = True
        variants.append(value)
        for value in variants:
            with self.assertRaises(ValueError):
                native.signal_diagnostic(
                    json.dumps({"publisher_signal_diagnostic": value}).encode()
                )

    def test_undecodable_child_summary_still_exposes_only_numeric_diagnostics(self):
        result = SimpleNamespace(returncode=1, stdout=b"PRIVATE", stderr=b"PRIVATE")
        diagnostic = signals.public_diagnostic(result, "a" * 64)
        self.assertFalse(diagnostic["summary_decoded"])
        self.assertIsNone(diagnostic["reported_tests"])
        self.assertEqual(diagnostic["failed_cases"], [])
        self.assertNotIn("PRIVATE", json.dumps(diagnostic))
        value = passed()
        value["outcomes"].append(None)
        result.stdout = json.dumps(value).encode()
        diagnostic = signals.public_diagnostic(result, "a" * 64)
        self.assertFalse(diagnostic["summary_decoded"])
        self.assertIsNone(diagnostic["reported_tests"])

    def test_exact_collection_and_old_five_selectors_retained(self):
        expected = {
            "status": "passed",
            "tests": 48,
            "failures": 0,
            "errors": 0,
            "skipped": 0,
        }
        self.assertEqual(signals.validate(passed(), "a" * 64), expected)
        self.assertEqual(
            native.result_counts(json.dumps(expected).encode(), "signals48"), expected
        )
        for suite, count, script in (
            ("protocol80", 80, "run_retirement_protocol.py"),
            ("archival9", 9, "run_retirement_archival.py"),
            ("operator77", 77, "run_retirement_operator.py"),
            ("fixtures36", 36, "run_retirement_fixture_guards.py"),
            ("backups56", 56, "run_retirement_backup_models.py"),
        ):
            self.assertEqual(
                native.SUITES[suite], (count, "/checks/tools/checks/" + script)
            )
            with self.assertRaises(ValueError):
                native.result_counts(json.dumps(expected).encode(), suite)

    def test_missing_duplicate_reordered_extra_or_false_cases_rejected(self):
        original = passed()
        variants = []
        value = copy.deepcopy(original)
        value["outcomes"].pop()
        variants.append(value)
        value = copy.deepcopy(original)
        value["outcomes"][1] = copy.deepcopy(value["outcomes"][0])
        variants.append(value)
        value = copy.deepcopy(original)
        value["outcomes"].reverse()
        variants.append(value)
        value = copy.deepcopy(original)
        value["outcomes"].append(copy.deepcopy(value["outcomes"][0]))
        variants.append(value)
        value = copy.deepcopy(original)
        value["outcomes"][0]["passed"] = False
        variants.append(value)
        for value in variants:
            with self.subTest(outcomes=len(value["outcomes"])):
                with self.assertRaises(RuntimeError):
                    signals.validate(value, "a" * 64)

    def test_skipped_external_wrong_source_or_impossible_native_claim_rejected(self):
        for key, new in (
            ("tests", True),
            ("passed", 47),
            ("failed", 1),
            ("source_sha256", "b" * 64),
            ("launcher_sha256", "b" * 64),
            ("external_posix_delivery", {"status": "not_run", "count": 0}),
            ("external_posix_delivery", {"status": "passed", "count": True}),
            ("focused_baseline", True),
            ("child_timeout_seconds", 11),
            ("native_cleanup_guaranteed", True),
        ):
            value = passed()
            value[key] = new
            with self.subTest(key=key, value=new):
                with self.assertRaises(RuntimeError):
                    signals.validate(value, "a" * 64)
        for key, value in (
            ("skipped", 1),
            ("errors", 1),
            ("tests", 47),
            ("tests", True),
        ):
            counts = {
                "status": "passed",
                "tests": 48,
                "failures": 0,
                "errors": 0,
                "skipped": 0,
            }
            counts[key] = value
            with self.assertRaises(ValueError):
                native.result_counts(json.dumps(counts).encode(), "signals48")

    def test_duplicate_JSON_field_cannot_hide_failure(self):
        with self.assertRaises(RuntimeError):
            signals.decode(b'{"failed":1,"failed":0}')

    def test_pristine_and_adapted_control_files_have_exact_reviewed_bytes(self):
        here = Path(__file__).parent / "retirement_fixture/publisher_signals"
        for name, digest in (
            ("test_installed_signals.py", signals.TEST_SHA),
            ("signal_child.py", signals.CHILD_SHA),
            ("operator_scope.py", signals.SCOPE_SHA),
            ("original/test_installed_signals.py", signals.ORIGINAL_TEST_SHA),
            ("original/signal_child.py", signals.ORIGINAL_CHILD_SHA),
        ):
            self.assertEqual(
                hashlib.sha256((here / name).read_bytes()).hexdigest(), digest
            )

    def test_adapter_reverses_only_four_reviewed_changes_to_exact_original_AST(self):
        here = Path(__file__).parent / "retirement_fixture/publisher_signals"
        original = ast.parse((here / "original/test_installed_signals.py").read_bytes())
        adapted = ast.parse((here / "test_installed_signals.py").read_bytes())
        found = 0
        for node in ast.walk(adapted):
            if isinstance(node, ast.Constant) and node.value == signals.LAUNCHER_SHA:
                node.value = (
                    "36c79abe23a0c7bc09538e5ba6368e10e396bbf7729caa2228f49dea52479e75"
                )
                found += 1
        self.assertEqual(found, 1)
        self.assertEqual(ast.dump(original), ast.dump(adapted))
        original = ast.parse((here / "original/signal_child.py").read_bytes())
        adapted = ast.parse((here / "signal_child.py").read_bytes())
        main = next(
            n
            for n in adapted.body
            if isinstance(n, ast.FunctionDef) and n.name == "main"
        )
        wanted = "load('operator_scope', Path(__file__).with_name('operator_scope.py'))"
        remove = [
            n
            for n in main.body
            if isinstance(n, ast.Expr) and ast.unparse(n.value) == wanted
        ]
        self.assertEqual(len(remove), 1)
        main.body.remove(remove[0])
        model = next(
            n
            for n in main.body
            if isinstance(n, ast.ClassDef) and n.name == "ModelDocker"
        )
        init = next(
            n
            for n in model.body
            if isinstance(n, ast.FunctionDef) and n.name == "__init__"
        )
        self.assertEqual(init.args.kwarg.arg, "kwargs")
        init.args.kwarg = None
        self.assertEqual(ast.unparse(init.body[0]), "super().__init__(**kwargs)")
        init.body[0].value.keywords = []
        assignment = next(
            n
            for n in main.body
            if isinstance(n, ast.Assign)
            and ast.unparse(n.targets[0]) == "operator_files.PRIVATE"
        )
        self.assertEqual(ast.unparse(assignment.value), "launcher.PRIVATE")
        assignment.value = ast.parse(
            'ModelPath("/public-model/retirement")', mode="eval"
        ).body
        self.assertEqual(ast.dump(original), ast.dump(adapted))


if __name__ == "__main__":
    unittest.main()
