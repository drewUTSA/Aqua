"""Frozen retrieval/SQL replay, explicitly not real-model accuracy evaluation.

The caller supplies a fixture schema and executor. Embeddings and semantic
rankings are frozen inputs; SQL is independently authored and expected rows
come from the synthetic fixture facts. No generation provider is constructed.
"""

from dataclasses import replace
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace
from typing import Any, Callable
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

from eval.replay_data import ReplayDenied, load  # noqa: E402


class FrozenLookup:
    """Accept exactly the production two-query retrieval protocol."""

    def __init__(self, case: dict, budget: Any) -> None:
        self.case, self.budget = case, budget
        self.embeddings = self.lookups = self.connections = 0

    def embed(self, question: str, settings: Any, client: Any) -> list[float]:
        if question != self.case["question"] or self.embeddings:
            raise ReplayDenied("replay_embedding_protocol")
        self.budget.provider("embedding")
        self.embeddings += 1
        return [0.0] * 768

    def connect(self, settings: Any) -> "FrozenLookup":
        if self.connections:
            raise ReplayDenied("replay_lookup_connection_budget")
        self.connections += 1
        return self

    def __enter__(self) -> "FrozenLookup":
        return self

    def __exit__(self, *args: Any) -> bool:
        return False

    def execute(self, query: str, args: tuple) -> Any:
        from nl2sql.retrieval import select

        expected = (select._TABLES_SQL, select._EXAMPLES_SQL)
        if (
            self.lookups >= 2
            or query != expected[self.lookups]
            or args[2] != (4 if not self.lookups else 3)
        ):
            raise ReplayDenied("replay_lookup_protocol")
        self.lookups += 1
        if self.lookups == 1:
            return [(name,) for name in self.case["nearest"]]
        return SimpleNamespace(fetchall=lambda: [])


def replay_case(
    case: dict, schema: Any, settings: Any, executor: Callable, hybrid: bool
) -> dict:
    """Run actual retrieval, validation and supplied real fixture execution."""
    from nl2sql.control import Budget, CURRENT
    from nl2sql.errors import ContextDenied
    from nl2sql.retrieval import select
    from nl2sql.validate import UnsafeQueryError, validate_sql

    budget = Budget(time.monotonic() + 10, lambda stage: None)
    token = CURRENT.set(budget)
    frozen = FrozenLookup(case, budget)
    status, executions = "unexpected_failure", 0
    try:
        with (
            patch.object(select, "embed_query", frozen.embed),
            patch.object(select, "connect", frozen.connect),
        ):
            try:
                context = select.VectorRetriever(
                    replace(settings, retrieval_hybrid_enabled=hybrid)
                ).select(case["question"], schema)
            except ContextDenied:
                status = "scope_denied"
            else:
                if not set(case["tables"]) <= set(context.tables):
                    status = "context_abstention"
                else:
                    # A frozen answer is replayed, never represented as generation.
                    budget.provider("frozen_sql_replay")
                    try:
                        query = validate_sql(case["sql"], allowed_tables=context.tables)
                    except UnsafeQueryError:
                        status = "sql_denied"
                    else:
                        executions += 1
                        result = executor(query, settings, max_rows=10)
                        status = (
                            "rows_match"
                            if result.rows == [tuple(r) for r in case["expected"]]
                            and not result.truncated
                            else "rows_mismatch"
                        )
        required = {"scope_denial": "scope_denied", "sql_denial": "sql_denied"}
        if case["kind"] in required:
            passed = status == required[case["kind"]]
        elif hybrid:
            # Every answer fixture deliberately names its target identifiers.
            # Losing lexical recovery must fail even though baseline abstention
            # remains a reported frozen-input measurement, never an accuracy pass.
            passed = status == "rows_match"
        else:
            passed = status in {"rows_match", "context_abstention"}
        if status.endswith("denied") and executions:
            passed = False
        expected_calls = 1 if status in {"scope_denied", "context_abstention"} else 2
        if (frozen.embeddings, frozen.lookups, frozen.connections) != (
            1,
            2,
            1,
        ) or budget.calls != expected_calls:
            raise ReplayDenied("replay_call_budget")
        return {
            "id": case["id"],
            "status": status,
            "passed": passed,
            "embedding_replays": frozen.embeddings,
            "lookup_replays": frozen.lookups,
            "frozen_provider_calls": budget.calls,
            "sql_executions": executions,
            "real_provider_calls": 0,
        }
    finally:
        CURRENT.reset(token)


def qualify(cases: list[dict], schema: Any, settings: Any, executor: Callable) -> dict:
    """Score test entries only; train records never enter retrieval or execution."""
    selected = [c for c in cases if c["split"] == "test"]
    if not selected:
        raise ReplayDenied("replay_no_test_cases")
    modes = {}
    for name, enabled in (("semantic_frozen", False), ("hybrid_frozen", True)):
        records = [
            replay_case(case, schema, settings, executor, enabled) for case in selected
        ]
        modes[name] = {
            "cases": records,
            "test_cases": len(records),
            "rows_match": sum(r["status"] == "rows_match" for r in records),
            "context_abstentions": sum(
                r["status"] == "context_abstention" for r in records
            ),
            "denials": sum(r["status"].endswith("denied") for r in records),
        }
    return {
        "status": (
            "passed"
            if all(r["passed"] for mode in modes.values() for r in mode["cases"])
            else "failed"
        ),
        "kind": "frozen_synthetic_retrieval_sql_replay",
        "real_model_quality_measured": False,
        "semantic_embeddings_frozen": True,
        "generation": "independently_authored_frozen_sql",
        "training_cases_excluded": sum(c["split"] == "train" for c in cases),
        "modes": modes,
    }


def main() -> int:
    """Closed container entry point; no caller-supplied URL, SQL or output path."""
    import os

    if sys.argv[1:] not in (["bank"], ["pagila"]):
        raise ReplayDenied("replay_fixture_selector")
    dataset = sys.argv[1]
    os.environ["AQUA_TEST_DATASET"] = dataset
    sys.path.insert(0, str(ROOT / "backend/tests"))
    from safety import install

    install()  # Discard inherited service config and prohibit external networks.
    from nl2sql.config import Settings
    from nl2sql.db import connect
    from nl2sql.execute import execute
    from nl2sql.schema import load_schema

    cases, digest = load(
        (ROOT / "tools/checks/fixtures/ai_replay_dataset.jsonl").read_bytes()
    )
    selected = [c for c in cases if c["dataset"] == dataset]
    tests = [c for c in selected if c["split"] == "test"]
    if len(tests) < 12 or not any(c["split"] == "train" for c in selected):
        raise ReplayDenied("replay_fixture_split_missing")
    if {c["kind"] for c in tests} != {"answer", "scope_denial", "sql_denial"}:
        raise ReplayDenied("replay_fixture_denial_control_missing")
    settings = Settings(
        database_url=f"postgresql://nl2sql_reader@127.0.0.1:5432/aqua_test_{dataset}",
        llm_fallback=False,
    )
    with connect(settings) as conn:
        schema = load_schema(conn)
    report = qualify(selected, schema, settings, execute)
    report.update(dataset=dataset, dataset_sha256=digest)
    print(json.dumps(report, sort_keys=True))
    return int(report["status"] != "passed")


if __name__ == "__main__":
    raise SystemExit(main())
