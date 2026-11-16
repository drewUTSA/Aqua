"""Paired experiment receipts cannot hide configuration drift or case omission."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from eval.compare_experiments import (
    ComparisonDenied,
    HASH_FIELDS,
    compare_experiments,
)  # noqa: E402


def raw(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value):
    return hashlib.sha256(value).hexdigest()


DATA = [
    {"id": str(i), "split": "test", "question": f"synthetic {i}", "sql": "SELECT 1"}
    for i in range(20)
]
DATASET = b"\n".join(raw(item) for item in DATA)
RUN = b"\n".join(
    raw(
        {
            "id": item["id"],
            "question": item["question"],
            "gold_sql": item["sql"],
            "status": "ok",
            "exact": True,
            "seconds": 1.0,
            "elapsed_seconds": 1.0,
            "provider_calls": 1,
        }
    )
    for item in DATA
)


def experiment(enabled):
    return {
        **{name: "a" * 64 for name in (*HASH_FIELDS, "config_sha256")},
        "dataset_sha256": digest(DATASET),
        "case_count": 20,
        "schema_version": 1,
        "kind": "evaluation_experiment",
        "retrieval": True,
        "hybrid": enabled,
        "deadline_seconds": 120,
        "provider_call_limit": 4,
        "production_activation_authorized": False,
        "index_revision_attested": False,
        "model_revision_attested": False,
        "data_revision_attested": False,
    }


def receipt(item, run=RUN):
    return raw(
        {
            "experiment": item,
            "experiment_sha256": digest(raw(item)),
            "results_sha256": digest(run),
            "cases": 20,
        }
    )


class ExperimentGate(unittest.TestCase):
    def test_complete_matching_declared_pair_passes_without_authorizing_release(self):
        result = compare_experiments(
            DATASET, RUN, RUN, receipt(experiment(False)), receipt(experiment(True))
        )
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["production_activation_authorized"])
        self.assertFalse(result["index_revision_attested"])
        self.assertNotIn("synthetic", json.dumps(result))

    def test_every_semantic_identity_drift_is_denied(self):
        for field in HASH_FIELDS:
            candidate = experiment(True)
            candidate[field] = "b" * 64
            with self.subTest(field=field), self.assertRaises(ComparisonDenied):
                compare_experiments(
                    DATASET, RUN, RUN, receipt(experiment(False)), receipt(candidate)
                )

    def test_unrecorded_index_and_bad_budget_or_retrieval_are_denied(self):
        for field, value in (
            ("index_revision", None),
            ("deadline_seconds", 121),
            ("provider_call_limit", True),
            ("retrieval", False),
            ("hybrid", False),
            ("case_count", 19),
        ):
            candidate = experiment(True)
            candidate[field] = value
            with self.subTest(field=field), self.assertRaises(ComparisonDenied):
                compare_experiments(
                    DATASET, RUN, RUN, receipt(experiment(False)), receipt(candidate)
                )

    def test_modified_results_or_receipt_bytes_are_denied(self):
        value = json.loads(receipt(experiment(True)))
        value["experiment"]["hybrid"] = False
        for changed_run, changed_receipt in (
            (RUN + b"\n", receipt(experiment(True))),
            (RUN, raw(value)),
        ):
            with self.assertRaises(ComparisonDenied):
                compare_experiments(
                    DATASET,
                    RUN,
                    changed_run,
                    receipt(experiment(False)),
                    changed_receipt,
                )

    def test_missing_case_fails_even_with_a_rehashed_receipt(self):
        candidate = b"\n".join(RUN.splitlines()[:-1])
        changed = copy.deepcopy(experiment(True))
        changed["case_count"] = 19
        value = json.loads(receipt(changed, candidate))
        value["cases"] = 19
        with self.assertRaises(ComparisonDenied):
            compare_experiments(
                DATASET, RUN, candidate, receipt(experiment(False)), raw(value)
            )

    def test_duplicate_receipt_fields_and_oversized_receipts_are_denied(self):
        for changed in (b'{"cases":20,"cases":20}', b" " * 65537):
            with self.assertRaises(ComparisonDenied):
                compare_experiments(
                    DATASET, RUN, RUN, receipt(experiment(False)), changed
                )

    def test_actual_budget_violations_including_outages_are_denied(self):
        for field, value in (
            ("elapsed_seconds", 121),
            ("elapsed_seconds", float("inf")),
            ("elapsed_seconds", True),
            ("provider_calls", 5),
            ("provider_calls", True),
        ):
            for outage in (True, False):
                changed = [json.loads(line) for line in RUN.splitlines()]
                changed[0][field] = value
                if outage:
                    changed[0].update(status="outage", exact=False, seconds=None)
                candidate = b"\n".join(raw(row) for row in changed)
                with (
                    self.subTest(field=field, outage=outage),
                    self.assertRaises(ComparisonDenied),
                ):
                    compare_experiments(
                        DATASET,
                        RUN,
                        candidate,
                        receipt(experiment(False)),
                        receipt(experiment(True), candidate),
                    )

    def test_latency_cannot_disagree_with_the_same_run_elapsed_measurement(self):
        changed = [json.loads(line) for line in RUN.splitlines()]
        changed[0]["elapsed_seconds"] = 2
        candidate = b"\n".join(raw(row) for row in changed)
        with self.assertRaises(ComparisonDenied):
            compare_experiments(
                DATASET,
                RUN,
                candidate,
                receipt(experiment(False)),
                receipt(experiment(True), candidate),
            )


if __name__ == "__main__":
    unittest.main()
