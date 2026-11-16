"""Evaluator receipts and per-case budgets use stand-ins, never providers."""

from dataclasses import replace
import json
import io

import pytest

from eval import run_eval
from eval.experiment import canonical, digest, experiment, source_identity, write_json
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT, ExecutionStopped
from nl2sql.db import DatabaseError
from nl2sql.errors import ContextDenied
from nl2sql.llm import LLMError
from nl2sql.pipeline import Answer
from nl2sql.schema import Column, Schema, Table

CASE = {
    "id": "case-1",
    "difficulty": "easy",
    "split": "test",
    "question": "PRIVATE_QUESTION count films?",
    "sql": "SELECT count(*) FROM film",
}
SCHEMA = Schema(
    {"film": Table("film", (Column("id", "integer", True),), (), frozenset())}
)


def answer():
    return Answer(CASE["question"], CASE["sql"], rows=[(1,)], model="private-model")


def test_one_budget_covers_gold_pipeline_and_scoring_and_restores_parent(monkeypatch):
    clock = [10.0]
    monkeypatch.setattr(run_eval.time, "perf_counter", lambda: clock[0])
    budgets = []

    def gold(*args):
        budgets.append(CURRENT.get())
        clock[0] += 0.00001
        return [(1,)]

    def pipeline(*args, **kwargs):
        budgets.append(CURRENT.get())
        CURRENT.get().provider()
        clock[0] += 0.00002
        return answer()

    monkeypatch.setattr(run_eval, "run_gold", gold)
    monkeypatch.setattr(run_eval, "answer_question", pipeline)
    parent = Budget(99999999, lambda name: None)
    token = CURRENT.set(parent)
    try:
        result = run_eval.evaluate(CASE, Settings(), SCHEMA, None)
        assert CURRENT.get() is parent
    finally:
        CURRENT.reset(token)
    assert budgets[0] is budgets[1] and budgets[0] is not parent
    assert result["status"] == "ok" and result["exact"]
    assert 0 < result["seconds"] < 0.001
    assert result["provider_calls"] == 1
    assert result["stage_seconds"]["gold"] > 0


def test_provider_limit_is_not_reset_between_gold_and_pipeline(monkeypatch):
    def gold(*args):
        CURRENT.get().provider()
        return [(1,)]

    def pipeline(*args, **kwargs):
        for _ in range(4):
            CURRENT.get().provider()
        pytest.fail("fifth provider call was allowed")

    monkeypatch.setattr(run_eval, "run_gold", gold)
    monkeypatch.setattr(run_eval, "answer_question", pipeline)
    result = run_eval.evaluate(CASE, Settings(), SCHEMA, None)
    assert result["status"] == "budget_exhausted"
    assert result["provider_calls"] == 4 and not result["exact"]


def test_gold_work_cannot_renew_the_deadline(monkeypatch):
    clock = [1.0]
    monkeypatch.setattr(run_eval.time, "monotonic", lambda: clock[0])

    def gold(*args):
        clock[0] = 122
        return [(1,)]

    monkeypatch.setattr(run_eval, "run_gold", gold)
    monkeypatch.setattr(
        run_eval, "answer_question", lambda *a, **k: pytest.fail("expired case ran")
    )
    result = run_eval.evaluate(CASE, Settings(), SCHEMA, None)
    assert result["status"] == "budget_exhausted"
    assert not result["exact"] and CURRENT.get() is None


@pytest.mark.parametrize(
    "error,status",
    [
        (LLMError, "outage"),
        (DatabaseError, "outage"),
        (ContextDenied, "denied"),
        (RuntimeError, "evaluation_failed"),
    ],
)
def test_failure_before_or_during_pipeline_is_complete_and_sanitized(
    monkeypatch, error, status
):
    def fail(*args, **kwargs):
        raise error("PRIVATE_EXCEPTION credential and query contents")

    monkeypatch.setattr(run_eval, "run_gold", fail)
    result = run_eval.evaluate(CASE, Settings(), SCHEMA, None)
    assert result["status"] == status
    assert not result["exact"] and not result["lenient"]
    assert (result["seconds"] is None) is (status == "outage")
    assert "PRIVATE_EXCEPTION" not in json.dumps(result)
    assert CURRENT.get() is None


def test_pipeline_failure_does_not_return_success_after_scoring(monkeypatch):
    monkeypatch.setattr(run_eval, "run_gold", lambda *args: [(1,)])
    monkeypatch.setattr(run_eval, "answer_question", lambda *args, **kwargs: answer())
    monkeypatch.setattr(
        run_eval,
        "lenient_match",
        lambda *args: (_ for _ in ()).throw(ExecutionStopped("PRIVATE")),
    )
    result = run_eval.evaluate(CASE, Settings(), SCHEMA, None)
    assert result["status"] == "budget_exhausted"
    assert not result["exact"] and "PRIVATE" not in result["error"]


def test_hybrid_argument_without_retrieval_fails_before_settings(monkeypatch):
    monkeypatch.setattr(
        run_eval, "load_settings", lambda: pytest.fail("read live settings")
    )
    with pytest.raises(SystemExit) as error:
        run_eval.main(["--hybrid", "on"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "arguments,expected",
    [([], False), (["--retrieval"], False), (["--retrieval", "--hybrid", "on"], True)],
)
def test_cli_uses_explicit_flag_and_writes_hash_only_create_only_receipts(
    monkeypatch, tmp_path, capsys, arguments, expected
):
    dataset = tmp_path / "private-dataset.jsonl"
    dataset.write_text(json.dumps(CASE) + "\n")
    observed = []
    monkeypatch.setattr(
        run_eval,
        "load_settings",
        lambda: Settings(
            retrieval_hybrid_enabled=True,
            database_url="PRIVATE_DSN",
            gemini_api_key="PRIVATE_KEY",
        ),
    )
    monkeypatch.setattr(run_eval, "get_schema", lambda settings: SCHEMA)
    monkeypatch.setattr(run_eval, "source_identity", lambda root: "a" * 64)
    monkeypatch.setattr(run_eval, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(run_eval, "run_gold", lambda *args: [(1,)])

    def pipeline(question, settings, schema, **kwargs):
        observed.append(settings)
        return answer()

    monkeypatch.setattr(run_eval, "answer_question", pipeline)
    assert (
        run_eval.main(
            ["--dataset", str(dataset), "--data-revision", "d" * 64, *arguments]
        )
        == 0
    )
    assert observed[0].retrieval_hybrid_enabled is expected
    receipt_path = next((tmp_path / "results").glob("*.receipt.json"))
    receipt = json.loads(receipt_path.read_text())
    assert receipt["experiment"]["hybrid"] is expected
    assert receipt["experiment"]["index_revision"] is None
    assert not receipt["experiment"]["index_revision_attested"]
    assert receipt["experiment"]["data_revision"] == "d" * 64
    assert receipt["experiment"]["data_revision_attested"] is False
    public = receipt_path.read_text() + capsys.readouterr().out
    assert all(
        secret not in public
        for secret in (
            "PRIVATE_DSN",
            "PRIVATE_KEY",
            CASE["question"],
            CASE["sql"],
            "private-model",
        )
    )
    record = json.loads(next((tmp_path / "results").glob("*.jsonl")).read_text())
    assert record["question"] == CASE["question"] and record["gold_sql"] == CASE["sql"]
    assert record["status"] == "ok" and record["seconds"] > 0
    with pytest.raises(FileExistsError):
        write_json(receipt_path, {"replace": True})


def test_receipt_binds_semantics_but_excludes_secrets_and_is_immutable():
    settings = Settings(gemini_api_key="PRIVATE_KEY", database_url="PRIVATE_DSN")

    def make(selected=settings, schema=SCHEMA, cases=None):
        return experiment(
            b"dataset bytes",
            cases or [CASE],
            selected,
            schema,
            source_sha256="a" * 64,
            retrieval=True,
        )

    original = make()
    changed_secret = make(
        replace(settings, gemini_api_key="other", database_url="different")
    )
    assert original == changed_secret
    assert original != make(replace(settings, retrieval_hybrid_enabled=True))
    assert (
        original.metadata()["paired_config_sha256"]
        == make(replace(settings, retrieval_hybrid_enabled=True)).metadata()[
            "paired_config_sha256"
        ]
    )
    assert (
        original.metadata()["endpoint_sha256"]
        != make(replace(settings, ollama_base_url="http://127.0.0.1:1234")).metadata()[
            "endpoint_sha256"
        ]
    )
    assert original.metadata()["model_revision_attested"] is False
    assert original != make(replace(settings, ollama_model="different-model"))
    assert original != make(cases=[dict(CASE, question="different question")])
    metadata = original.metadata()
    metadata["hybrid"] = True
    assert not original.metadata()["hybrid"]
    assert "PRIVATE" not in original.payload and "film" not in original.payload


def test_source_identity_binds_named_source_and_excludes_env(tmp_path):
    for name in (
        "backend/nl2sql/config.py",
        "eval/run_eval.py",
        "backend/requirements.txt",
        "tools/checks/requirements-runtime.lock",
        "db/04_retrieval.sql",
    ):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("original")
    before = source_identity(tmp_path)
    (tmp_path / ".env").write_text("PRIVATE_KEY")
    assert source_identity(tmp_path) == before
    (tmp_path / "eval/run_eval.py").write_text("changed")
    assert source_identity(tmp_path) != before


def test_dataset_read_is_bounded_before_json_parsing():
    class Source:
        def open(self, mode):
            assert mode == "rb"
            return io.BytesIO(b"x" * (run_eval.MAX_BYTES + 100))

    raw = run_eval.read_dataset(Source())
    assert len(raw) == run_eval.MAX_BYTES + 1
    with pytest.raises(ValueError):
        run_eval.select_items(raw, "test")


def test_unknown_requested_case_fails_before_database_setup(monkeypatch, tmp_path):
    dataset = tmp_path / "set.jsonl"
    dataset.write_text(json.dumps(CASE) + "\n")
    monkeypatch.setattr(run_eval, "load_settings", Settings)
    monkeypatch.setattr(
        run_eval, "get_schema", lambda settings: pytest.fail("database setup")
    )
    with pytest.raises(SystemExit) as error:
        run_eval.main(["--dataset", str(dataset), "--ids", "case-1,missing"])
    assert error.value.code == 2


def test_generated_run_and_receipt_contract_reaches_paired_comparison(monkeypatch):
    from eval.compare_experiments import compare_experiments

    cases = [
        dict(CASE, id=f"test-{i}", question=f"synthetic question {i}")
        for i in range(20)
    ]
    dataset = b"\n".join(canonical(item).encode() for item in cases)
    clock = iter(i / 100 for i in range(1000))
    monkeypatch.setattr(run_eval.time, "perf_counter", lambda: next(clock))
    monkeypatch.setattr(run_eval, "run_gold", lambda *args: [(1,)])
    monkeypatch.setattr(run_eval, "answer_question", lambda *args, **kwargs: answer())
    outputs, receipts = [], []
    for enabled in (False, True):
        settings = Settings(retrieval_hybrid_enabled=enabled)
        result = b"\n".join(
            canonical(run_eval.evaluate(item, settings, SCHEMA, object())).encode()
            for item in cases
        )
        declaration = experiment(
            dataset,
            cases,
            settings,
            SCHEMA,
            source_sha256="a" * 64,
            retrieval=True,
            index_revision="b" * 64,
            data_revision="d" * 64,
        )
        outputs.append(result)
        receipts.append(
            canonical(
                {
                    "experiment_sha256": declaration.sha256,
                    "results_sha256": digest(result),
                    "cases": len(cases),
                    "experiment": declaration.metadata(),
                }
            ).encode()
        )
    compared = compare_experiments(dataset, *outputs, *receipts)
    assert compared["status"] == "passed"
    assert not compared["production_activation_authorized"]
    assert not compared["model_revision_attested"]


def test_ordered_case_metadata_requires_a_boolean():
    for value in (0, 1, "false", None, [], {}):
        raw = canonical(dict(CASE, ordered=value)).encode()
        with pytest.raises(ValueError, match="dataset_case_invalid"):
            run_eval.select_items(raw, "test")
    for value in (True, False):
        assert (
            run_eval.select_items(
                canonical(dict(CASE, ordered=value)).encode(), "test"
            )[0]["ordered"]
            is value
        )


def test_gold_check_has_budget_and_never_echoes_exception_or_question(
    monkeypatch, capsys
):
    def fail(*args):
        assert CURRENT.get() is not None
        raise RuntimeError("PRIVATE_EXCEPTION")

    monkeypatch.setattr(run_eval, "run_gold", fail)
    assert run_eval.check_gold([CASE], Settings(), SCHEMA) == 1
    output = capsys.readouterr().out
    assert "PRIVATE" not in output and CURRENT.get() is None
