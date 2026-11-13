"""Holdout gates reject selection bias, leaked training cases and bad timings."""

import copy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.compare_runs import ComparisonDenied, compare  # noqa: E402

DATA = [
    {"id": str(i), "split": "test", "question": f"synthetic {i}", "sql": "SELECT 1"}
    for i in range(20)
]
RUN = [
    {
        "id": item["id"],
        "question": item["question"],
        "gold_sql": item["sql"],
        "status": "ok",
        "exact": True,
        "seconds": 1.0,
    }
    for item in DATA
]


def raw(items):
    return b"\n".join(json.dumps(item).encode() for item in items)


class HoldoutGate(unittest.TestCase):
    def test_equal_complete_runs_pass_without_echoing_questions(self):
        report = compare(raw(DATA), raw(RUN), raw(RUN))
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["candidate"]["correct"], 20)
        self.assertNotIn("synthetic", json.dumps(report))
        self.assertFalse(report["production_activation_authorized"])

    def test_missing_duplicate_or_training_cases_cannot_inflate_accuracy(self):
        for changed in (RUN[:-1], RUN + [RUN[0]], RUN + [dict(RUN[0], id="training")]):
            with self.subTest(count=len(changed)), self.assertRaises(ComparisonDenied):
                compare(raw(DATA), raw(RUN), raw(changed))

    def test_modified_gold_and_question_are_denied(self):
        for field in ("question", "gold_sql"):
            candidate = copy.deepcopy(RUN)
            candidate[0][field] = "tampered"
            with self.subTest(field=field), self.assertRaises(ComparisonDenied):
                compare(raw(DATA), raw(RUN), raw(candidate))

    def test_regression_or_latency_increase_fails(self):
        for field, value in (("exact", False), ("seconds", 2.0)):
            candidate = [dict(item, **{field: value}) for item in RUN]
            with self.subTest(field=field):
                self.assertEqual(
                    compare(raw(DATA), raw(RUN), raw(candidate))["status"], "regression"
                )

    def test_outages_stay_in_accuracy_denominator(self):
        candidate = copy.deepcopy(RUN)
        candidate[0].update(status="outage", seconds=None, exact=False)
        report = compare(raw(DATA), raw(RUN), raw(candidate))
        self.assertEqual(report["status"], "regression")
        self.assertEqual(report["candidate"]["accuracy"], 0.95)
        self.assertEqual(report["candidate"]["timed_cases"], 19)

    def test_invalid_or_unbounded_timings_and_fake_success_are_denied(self):
        for value in (float("nan"), float("inf"), -1, 0, 121, True, None):
            candidate = copy.deepcopy(RUN)
            candidate[0]["seconds"] = value
            with self.subTest(value=value), self.assertRaises(ComparisonDenied):
                compare(raw(DATA), raw(RUN), raw(candidate))
        candidate[0].update(status="denied", seconds=1)
        with self.assertRaises(ComparisonDenied):
            compare(raw(DATA), raw(RUN), raw(candidate))

    def test_tiny_holdouts_and_ambiguous_json_are_denied(self):
        with self.assertRaises(ComparisonDenied):
            compare(raw(DATA[:1]), raw(RUN[:1]), raw(RUN[:1]))
        with self.assertRaises(ComparisonDenied):
            compare(raw(DATA), raw(RUN), b'{"id":"0","id":"1"}')


if __name__ == "__main__":
    unittest.main()
