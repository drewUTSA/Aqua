"""Replay protocol/denial tests; real SQL execution is a separate closed runner."""

import copy
import json
from types import SimpleNamespace

import pytest

from eval.replay import FrozenLookup, qualify, replay_case
from eval.replay_data import ReplayDenied, load
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.schema import Column, Schema, Table


def schema():
    return Schema(
        {
            name: Table(name, (Column(name + "_id", "integer", True),), (), frozenset())
            for name in ("account", "loan", "client", "card", "trans")
        }
    )


def case():
    return {
        "id": "synthetic-loan-count",
        "split": "test",
        "dataset": "bank",
        "question": "Count loan rows",
        "sql": "SELECT COUNT(*) FROM loan",
        "tables": ["loan"],
        "nearest": ["account", "client", "card", "trans"],
        "expected": [[0]],
        "kind": "answer",
    }


def dataset():
    cases = []
    for n in range(28):
        value = case() | {
            "id": f"synthetic-case-{n}",
            "split": "train" if n < 4 else "test",
        }
        cases.append(value)
    return cases


def encode(cases):
    return "\n".join(json.dumps(c) for c in cases).encode()


def test_frozen_semantic_abstains_and_actual_hybrid_recovers_identifier():
    executed = []

    def executor(query, settings, max_rows):
        executed.append(query.sql())
        assert max_rows == 10 and settings.database_url == ""
        return SimpleNamespace(rows=[(0,)], truncated=False)

    original = CURRENT.get()
    baseline = replay_case(case(), schema(), Settings(), executor, False)
    candidate = replay_case(case(), schema(), Settings(), executor, True)
    assert (
        baseline["status"] == "context_abstention" and baseline["sql_executions"] == 0
    )
    assert candidate["status"] == "rows_match" and candidate["sql_executions"] == 1
    assert len(executed) == 1 and CURRENT.get() is original
    assert candidate["embedding_replays"] == 1 and candidate["lookup_replays"] == 2
    assert (
        candidate["frozen_provider_calls"] == 2
        and candidate["real_provider_calls"] == 0
    )


@pytest.mark.parametrize("hybrid", [False, True])
@pytest.mark.parametrize("attack", ["scope", "write", "catalog"])
def test_denials_do_not_execute_sql_or_hide_unauthorized_hits(attack, hybrid):
    value = case()
    if attack == "scope":
        value.update(
            kind="scope_denial",
            nearest=["aqua_private.accounts", "account", "client", "card"],
        )
    else:
        value.update(
            kind="sql_denial",
            nearest=["loan", "account", "client", "card"],
            sql=(
                "DELETE FROM loan"
                if attack == "write"
                else "SELECT * FROM pg_catalog.pg_class"
            ),
        )

    def refused(*args, **kwargs):
        pytest.fail("denied replay performed SQL work")

    result = replay_case(value, schema(), Settings(), refused, hybrid)
    assert result["passed"] and result["sql_executions"] == 0
    assert result["status"] == ("scope_denied" if attack == "scope" else "sql_denied")


def test_wrong_rows_are_failure_and_training_cases_are_excluded():
    cases = dataset()
    calls = []

    def wrong(query, settings, max_rows):
        calls.append(query)
        return SimpleNamespace(rows=[(999,)], truncated=False)

    result = qualify(cases, schema(), Settings(), wrong)
    assert result["status"] == "failed" and result["training_cases_excluded"] == 4
    assert len(calls) == 24  # Only hybrid finds loan; train never executes.
    assert result["real_model_quality_measured"] is False
    assert all(m["test_cases"] == 24 for m in result["modes"].values())


def test_lost_hybrid_identifier_recovery_cannot_pass(monkeypatch):
    from nl2sql.retrieval import select

    monkeypatch.setattr(
        select, "hybrid_tables", lambda schema, nearest, question, limit: nearest
    )

    def refused(*args, **kwargs):
        pytest.fail("missing context must not execute the frozen SQL")

    result = replay_case(case(), schema(), Settings(), refused, True)
    assert result["status"] == "context_abstention" and not result["passed"]


def test_empty_test_selection_cannot_produce_a_passing_report():
    with pytest.raises(ReplayDenied, match="no_test_cases"):
        qualify([case() | {"split": "train"}], schema(), Settings(), None)


@pytest.mark.parametrize(
    "attack",
    [
        "duplicate_id",
        "unknown_field",
        "training_only",
        "too_many",
        "long_question",
        "bad_dataset",
        "wide_expected",
        "foreign_field",
        "large_bytes",
        "duplicate_json",
        "nested_relation",
    ],
)
def test_loader_rejects_ambiguous_unbounded_or_wrong_scope_artifacts(attack):
    cases = copy.deepcopy(dataset())
    if attack == "duplicate_id":
        cases[1]["id"] = cases[0]["id"]
    elif attack == "unknown_field":
        cases[0]["provider"] = "live"
    elif attack == "training_only":
        for value in cases:
            value["split"] = "train"
    elif attack == "too_many":
        cases = cases * 3
    elif attack == "long_question":
        cases[0]["question"] = "x" * 2001
    elif attack == "bad_dataset":
        cases[0]["dataset"] = "production"
    elif attack == "wide_expected":
        cases[0]["expected"] = [[0] * 5]
    elif attack == "foreign_field":
        cases[0]["database_url"] = "not-accepted"
    elif attack == "nested_relation":
        cases[0]["nearest"] = [{"host": "not-accepted"}]
    raw = encode(cases)
    if attack == "large_bytes":
        raw = b" " * 262145
    elif attack == "duplicate_json":
        raw = raw.replace(b'"split": "train"', b'"split": "train", "split": "test"', 1)
    with pytest.raises(ReplayDenied):
        load(raw)


def test_loader_returns_digest_and_frozen_protocol_rejects_extra_calls():
    cases, digest = load(encode(dataset()))
    assert len(cases) == 28 and len(digest) == 64
    frozen = FrozenLookup(case(), Budget(float("inf"), lambda stage: None))
    frozen.embed(case()["question"], Settings(), None)
    with pytest.raises(ReplayDenied):
        frozen.embed(case()["question"], Settings(), None)
    with pytest.raises(ReplayDenied):
        frozen.execute("arbitrary query", ("fake", [], 4))
