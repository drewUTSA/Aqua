"""Deterministic provider/deadline and meaningful follow-up pipeline contracts."""

import json
import time

import httpx
import pytest

from nl2sql import control, llm, pipeline
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT, ExecutionStopped
from nl2sql.execute import QueryError, QueryResult
from nl2sql.llm import Completion, LLMError
from nl2sql.query_service import run
from nl2sql.schema import Column, Schema, Table

SCHEMA = Schema(
    {
        "film": Table(
            "film",
            (Column("film_id", "integer", True), Column("title", "text", True)),
            (),
            frozenset(),
        )
    }
)


def test_real_prompt_pipeline_resolves_an_ambiguous_followup_without_egressing_record_ids(
    monkeypatch,
):
    prompts = []

    def provider(prompt, *args):
        prompts.append(prompt)
        sql = (
            "SELECT title FROM film WHERE title LIKE 'A%'"
            if "List film titles" in prompt
            else "SELECT film_id FROM film"
        )
        return Completion(
            json.dumps({"sql": sql}), "PRIVATE_THOUGHT_MUST_NOT_EGRESS", "fixture-only"
        )

    def execute(query, settings, max_rows):
        sql = query.sql(dialect="postgres")
        return QueryResult(
            sql,
            ["title"] if "LIKE" in sql else ["film_id"],
            [("A film",)] if "LIKE" in sql else [(7,)],
            False,
        )

    monkeypatch.setattr(llm, "_complete_ollama", provider)
    monkeypatch.setattr(pipeline, "execute", execute)
    settings = Settings(
        database_url="fixture-only-no-network",
        llm_provider="ollama",
        llm_fallback=False,
    )

    def ask(history):
        budget = Budget(
            time.monotonic() + 10, lambda stage: None, history, "fixture-context"
        )
        token = CURRENT.set(budget)
        try:
            response, status = run(
                "Only those starting with A",
                "ollama",
                settings,
                "fixture-owner",
                1,
                0,
                schema_reader=lambda settings: SCHEMA,
                retriever_factory=lambda settings: None,
            )
            assert status == 200 and budget.calls == 1
            return response
        finally:
            CURRENT.reset(token)

    plain = ask([])
    contextual = ask(
        [
            {
                "question": "List film titles",
                "sql": "SELECT title FROM film",
                "message_id": "APP_PRIVATE_UUID",
                "rows": ["ROW_PRIVATE"],
                "thinking": "PRIVATE_THOUGHT_MUST_NOT_EGRESS",
            }
        ]
    )
    assert plain["sql"] != contextual["sql"] and "LIKE 'A%'" in contextual["sql"]
    assert contextual["tables"][0]["rows"] == [{"title": "A film"}]
    assert all(
        marker not in prompts[-1]
        for marker in [
            "APP_PRIVATE_UUID",
            "ROW_PRIVATE",
            "PRIVATE_THOUGHT_MUST_NOT_EGRESS",
        ]
    )
    assert "PRIVATE_THOUGHT_MUST_NOT_EGRESS" not in json.dumps(contextual)


def test_four_total_provider_calls_are_shared_by_fallback_and_sql_repair(monkeypatch):
    calls, executions = [], []

    def provider(prompt, settings, *args):
        calls.append(settings.llm_provider)
        if len(calls) < 4:
            raise LLMError("Synthetic transient outage", transient=True)
        return Completion('{"sql":"SELECT title FROM film"}', "", "fixture-only")

    def execute(query, *args, **kwargs):
        executions.append(query)
        raise QueryError("invalid_column")

    monkeypatch.setattr(llm, "_complete_gemini", provider)
    monkeypatch.setattr(llm, "_complete_ollama", provider)
    monkeypatch.setattr(pipeline, "execute", execute)
    settings = Settings(
        llm_provider="gemini",
        gemini_api_key="fixture-only",
        gemini_fallback_models=("gemma-fixture-a", "gemma-fixture-b"),
    )
    budget = Budget(time.monotonic() + 10, lambda stage: None)
    token = CURRENT.set(budget)
    try:
        with pytest.raises(ExecutionStopped, match="attempt_limit"):
            pipeline.answer_question("List film titles", settings, SCHEMA)
    finally:
        CURRENT.reset(token)
    assert len(calls) == budget.calls == 4 and len(executions) == 1


def test_elapsed_provider_time_does_not_start_a_fresh_fallback_deadline(monkeypatch):
    instant, calls = [100.0], []
    monkeypatch.setattr(control.time, "monotonic", lambda: instant[0])

    def stalled(*args):
        calls.append("first")
        instant[0] = 106.0
        raise LLMError("Synthetic transient timeout", transient=True)

    monkeypatch.setattr(llm, "_complete_gemini", stalled)
    monkeypatch.setattr(
        llm,
        "_complete_ollama",
        lambda *args: pytest.fail("expired fallback reached provider"),
    )
    budget = Budget(105.0, lambda stage: None)
    token = CURRENT.set(budget)
    try:
        with pytest.raises(ExecutionStopped, match="expired"):
            llm.complete(
                "Synthetic",
                Settings(llm_provider="gemini", gemini_api_key="fixture-only"),
            )
    finally:
        CURRENT.reset(token)
    assert calls == ["first"] and budget.calls == 1


def test_elapsed_sql_time_prevents_repair_from_receiving_a_new_budget(monkeypatch):
    instant, calls = [100.0], []
    monkeypatch.setattr(control.time, "monotonic", lambda: instant[0])

    def provider(*args):
        calls.append("first")
        return Completion('{"sql":"SELECT title FROM film"}', "", "fixture-only")

    def slow_query(*args, **kwargs):
        instant[0] = 106.0
        raise QueryError("invalid_column")

    monkeypatch.setattr(llm, "_complete_ollama", provider)
    monkeypatch.setattr(pipeline, "execute", slow_query)
    token = CURRENT.set(Budget(105.0, lambda stage: None))
    try:
        with pytest.raises(ExecutionStopped, match="expired"):
            pipeline.answer_question(
                "List titles",
                Settings(llm_provider="ollama", llm_fallback=False),
                SCHEMA,
            )
    finally:
        CURRENT.reset(token)
    assert calls == ["first"]


def test_controlled_gemini_disables_hidden_sdk_retries_and_bounds_output(monkeypatch):
    from google import genai
    from types import SimpleNamespace

    seen = {}

    class Client:
        def __init__(self, **kwargs):
            seen.update(kwargs)
            self.models = self

        def generate_content(self, **kwargs):
            seen["request"] = kwargs
            return SimpleNamespace(
                text='{"sql":"SELECT 1"}', model_version="fixture-only"
            )

        def close(self):
            seen["closed"] = True

    monkeypatch.setattr(genai, "Client", Client)
    budget = Budget(time.monotonic() + 20, lambda stage: None)
    token = CURRENT.set(budget)
    try:
        llm.complete(
            "Synthetic",
            Settings(
                llm_provider="gemini", gemini_api_key="fixture-only", llm_fallback=False
            ),
        )
    finally:
        CURRENT.reset(token)
    assert seen["http_options"].retry_options.attempts == 1
    assert 0 < seen["http_options"].timeout <= 20000
    assert seen["request"]["config"].max_output_tokens == 4096
    assert budget.calls == 1 and seen["closed"]


def test_controlled_ollama_stream_refuses_oversized_body_before_json_parse():
    requests = []

    def reply(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, content=b"x" * (1048576 + 1))

    token = CURRENT.set(Budget(time.monotonic() + 10, lambda stage: None))
    try:
        with httpx.Client(transport=httpx.MockTransport(reply)) as client:
            with pytest.raises(LLMError, match="budget"):
                llm.complete(
                    "Synthetic",
                    Settings(llm_provider="ollama", llm_fallback=False),
                    client=client,
                )
    finally:
        CURRENT.reset(token)
    assert requests[0]["options"]["num_predict"] == 4096
