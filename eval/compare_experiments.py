"""Offline hybrid comparison bound to declared experiment and result bytes.

Hashes detect mismatched artifacts, not forged provenance. This gate neither
attests a live index/model nor authorizes production activation.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import re

from eval.compare_runs import ComparisonDenied, MAX_BYTES, compare, records, unique

HASH_FIELDS = (
    "dataset_sha256",
    "selected_cases_sha256",
    "source_sha256",
    "schema_sha256",
    "allowlist_sha256",
    "paired_config_sha256",
    "model_sha256",
    "embedding_sha256",
    "endpoint_sha256",
    "index_revision",
    "data_revision",
)


def hashed(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def receipt(raw: bytes, results: bytes, dataset: bytes) -> dict:
    """Require a complete receipt bound to exactly the supplied run bytes."""
    if not 0 < len(raw) <= 65536:
        raise ComparisonDenied("receipt_budget_invalid")
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except (ValueError, UnicodeError, RecursionError):
        raise ComparisonDenied("receipt_invalid") from None
    if type(value) is not dict or set(value) != {
        "experiment_sha256",
        "results_sha256",
        "cases",
        "experiment",
    }:
        raise ComparisonDenied("receipt_invalid")
    item = value["experiment"]
    if type(item) is not dict:
        raise ComparisonDenied("experiment_invalid")
    try:
        canonical = json.dumps(
            item, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    except (ValueError, TypeError, RecursionError):
        raise ComparisonDenied("experiment_invalid") from None
    if value["experiment_sha256"] != hashed(canonical) or value[
        "results_sha256"
    ] != hashed(results):
        raise ComparisonDenied("receipt_binding_invalid")
    if any(
        type(item.get(name)) is not str or not re.fullmatch(r"[a-f0-9]{64}", item[name])
        for name in (*HASH_FIELDS, "config_sha256")
    ):
        raise ComparisonDenied("experiment_identity_required")
    measured = records(results)
    for record in measured:
        elapsed, calls = record.get("elapsed_seconds"), record.get("provider_calls")
        if (
            type(elapsed) not in (int, float)
            or not math.isfinite(elapsed)
            or not 0 < elapsed <= 120
            or type(calls) is not int
            or not 0 <= calls <= 4
            or (record.get("status") != "outage" and record.get("seconds") != elapsed)
        ):
            raise ComparisonDenied("measured_budget_invalid")
    count = len(measured)
    if (
        type(value["cases"]) is not int
        or value["cases"] != count
        or type(item.get("case_count")) is not int
        or item["case_count"] != count
        or item.get("dataset_sha256") != hashed(dataset)
        or type(item.get("schema_version")) is not int
        or item["schema_version"] != 1
        or item.get("kind") != "evaluation_experiment"
        or item.get("retrieval") is not True
        or type(item.get("hybrid")) is not bool
        or type(item.get("deadline_seconds")) is not int
        or item["deadline_seconds"] != 120
        or type(item.get("provider_call_limit")) is not int
        or item["provider_call_limit"] != 4
        or item.get("production_activation_authorized") is not False
        or item.get("index_revision_attested") is not False
        or item.get("model_revision_attested") is not False
        or item.get("data_revision_attested") is not False
    ):
        raise ComparisonDenied("experiment_contract_invalid")
    return item


def compare_experiments(
    dataset: bytes,
    baseline: bytes,
    candidate: bytes,
    baseline_receipt: bytes,
    candidate_receipt: bytes,
) -> dict:
    before = receipt(baseline_receipt, baseline, dataset)
    after = receipt(candidate_receipt, candidate, dataset)
    if before["hybrid"] is not False or after["hybrid"] is not True:
        raise ComparisonDenied("hybrid_off_on_pair_required")
    if any(before[name] != after[name] for name in HASH_FIELDS):
        raise ComparisonDenied("paired_experiment_mismatch")
    result = compare(dataset, baseline, candidate)
    return result | {
        "kind": "declared_experiment_paired_holdout_gate",
        "experiment_pair_bound": True,
        "baseline_receipt_sha256": hashed(baseline_receipt),
        "candidate_receipt_sha256": hashed(candidate_receipt),
        "model_revision_attested": False,
        "index_revision_attested": False,
        "data_revision_attested": False,
        "production_activation_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    for name in (
        "dataset",
        "baseline",
        "candidate",
        "baseline_receipt",
        "candidate_receipt",
    ):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    try:
        inputs = []
        for name in (
            "dataset",
            "baseline",
            "candidate",
            "baseline_receipt",
            "candidate_receipt",
        ):
            limit = 65536 if name.endswith("receipt") else MAX_BYTES
            with getattr(args, name).open("rb") as source:
                raw = source.read(limit + 1)
            if len(raw) > limit:
                raise ComparisonDenied("input_budget_invalid")
            inputs.append(raw)
        result = compare_experiments(*inputs)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    except (ComparisonDenied, OSError):
        print(
            json.dumps(
                {"status": "denied", "category": "experiment_comparison_invalid"}
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
