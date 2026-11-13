"""Offline paired holdout gate; never calls a model, database or network."""

import argparse
import hashlib
import json
import math
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_CASES = 2000


class ComparisonDenied(ValueError):
    """Fixed categories omit questions, SQL and result rows."""


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ComparisonDenied("duplicate_field")
        value[key] = item
    return value


def records(raw: bytes) -> list[dict]:
    if not raw or len(raw) > MAX_BYTES:
        raise ComparisonDenied("input_budget_invalid")
    try:
        result = [
            json.loads(line, object_pairs_hook=unique)
            for line in raw.splitlines()
            if line.strip()
        ]
    except (ValueError, UnicodeError, RecursionError):
        raise ComparisonDenied("input_invalid") from None
    if not 1 <= len(result) <= MAX_CASES or any(
        type(item) is not dict for item in result
    ):
        raise ComparisonDenied("case_budget_invalid")
    return result


def indexed(items):
    result = {}
    for item in items:
        key = item.get("id")
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or key in result:
            raise ComparisonDenied("case_identity_invalid")
        result[key] = item
    return result


def p95(values):
    return sorted(values)[math.ceil(len(values) * 0.95) - 1] if values else None


def compare(
    dataset: bytes,
    baseline: bytes,
    candidate: bytes,
    *,
    minimum: int = 20,
    max_latency_ratio: float = 1.2,
) -> dict:
    if (
        not 1 <= minimum <= MAX_CASES
        or not math.isfinite(max_latency_ratio)
        or max_latency_ratio < 1
    ):
        raise ComparisonDenied("threshold_invalid")
    all_cases = indexed(records(dataset))
    gold = {key: item for key, item in all_cases.items() if item.get("split") == "test"}
    if len(gold) < minimum:
        raise ComparisonDenied("holdout_too_small")
    runs = [indexed(records(raw)) for raw in (baseline, candidate)]
    summaries = []
    for run in runs:
        if set(run) != set(gold):
            raise ComparisonDenied("complete_same_holdout_required")
        timings = []
        correct = outages = 0
        for key, expected in gold.items():
            item = run[key]
            if item.get("question") != expected.get("question") or item.get(
                "gold_sql"
            ) != expected.get("sql"):
                raise ComparisonDenied("gold_binding_invalid")
            status, exact, seconds = (
                item.get("status"),
                item.get("exact"),
                item.get("seconds"),
            )
            if (
                not isinstance(status, str)
                or not 1 <= len(status) <= 64
                or type(exact) is not bool
                or (exact and status != "ok")
            ):
                raise ComparisonDenied("result_invalid")
            if status == "outage":
                if seconds is not None or exact:
                    raise ComparisonDenied("outage_invalid")
                outages += 1
            else:
                if (
                    type(seconds) not in (int, float)
                    or not math.isfinite(seconds)
                    or not 0 < seconds <= 120
                ):
                    raise ComparisonDenied("timing_invalid")
                timings.append(seconds)
            correct += exact
        summaries.append(
            {
                "cases": len(gold),
                "correct": correct,
                "accuracy": correct / len(gold),
                "outages": outages,
                "timed_cases": len(timings),
                "p95_seconds": p95(timings),
            }
        )
    before, after = summaries
    # Neither missing/outage timings nor failures disappear from accuracy.
    latency_ok = (
        before["p95_seconds"] is not None
        and after["p95_seconds"] is not None
        and after["p95_seconds"] <= before["p95_seconds"] * max_latency_ratio
    )
    accepted = (
        after["correct"] >= before["correct"]
        and after["outages"] <= before["outages"]
        and latency_ok
    )
    return {
        "status": "passed" if accepted else "regression",
        "kind": "offline_paired_holdout_gate",
        "dataset_sha256": hashlib.sha256(dataset).hexdigest(),
        "baseline_sha256": hashlib.sha256(baseline).hexdigest(),
        "candidate_sha256": hashlib.sha256(candidate).hexdigest(),
        "baseline": before,
        "candidate": after,
        "improved_cases": sum(
            not runs[0][key]["exact"] and runs[1][key]["exact"] for key in gold
        ),
        "regressed_cases": sum(
            runs[0][key]["exact"] and not runs[1][key]["exact"] for key in gold
        ),
        "max_p95_ratio": max_latency_ratio,
        "network_calls": 0,
        "production_activation_authorized": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("dataset", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--minimum", type=int, default=20)
    parser.add_argument("--max-latency-ratio", type=float, default=1.2)
    args = parser.parse_args()
    try:
        inputs = []
        for path in (args.dataset, args.baseline, args.candidate):
            with path.open("rb") as source:
                inputs.append(source.read(MAX_BYTES + 1))
        result = compare(
            *inputs, minimum=args.minimum, max_latency_ratio=args.max_latency_ratio
        )
        print(json.dumps(result, sort_keys=True))
        return 0 if result["status"] == "passed" else 1
    except (ComparisonDenied, OSError):
        print(json.dumps({"status": "denied", "category": "comparison_invalid"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
