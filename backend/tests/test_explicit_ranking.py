"""Exercise the employee opt-in through its actual query service with no provider."""

import time
from unittest.mock import Mock

import pytest

from nl2sql import explicit_ranking, query_service
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.execute import QueryError, QueryResult
from nl2sql.schema import Column, Schema, Table

GROUP = Column("aisle", "text", True)
VALUE = Column("volume", "numeric", True)
TABLE = Table("dispatch", (GROUP, VALUE), (), frozenset())
SCHEMA = Schema({"dispatch": TABLE})
SETTINGS = Settings(llm_provider="gemini", gemini_api_key="", retrieval=True)
COMMAND = (
    "Rank groups: From dispatch, show the top 2 aisles by row count, including ties."
)


def request(question, **kwargs):
    return query_service.run(
        question,
        None,
        SETTINGS,
        "employee",
        5,
        2,
        include_metadata=kwargs.pop("include_metadata", True),
        first_chat_input=kwargs.pop("first_chat_input", True),
        answerer=Mock(side_effect=AssertionError("unplanned provider")),
        retriever_factory=Mock(side_effect=AssertionError("unplanned embedding")),
        schema_reader=kwargs.pop("schema_reader", lambda _: SCHEMA),
        **kwargs,
    )


@pytest.mark.parametrize("direction,level", [("top", "highest"), ("bottom", "lowest")])
@pytest.mark.parametrize("metric", ["row count", "total volume"])
@pytest.mark.parametrize("policy", ["peers", "exact", "levels"])
def test_form_runs_the_validated_policy(monkeypatch, direction, level, metric, policy):
    clauses = {
        "peers": f"show the {direction} 2 aisles by {metric}, including ties.",
        "exact": f"show exactly the {direction} 2 aisles by {metric}.",
        "levels": f"which aisles have one of the {level} 2 distinct {metric} values?",
    }
    question = f"Rank groups: From dispatch, {clauses[policy]}"
    execute = Mock(
        return_value=QueryResult("checked", ["aisle", "value"], [("A", 4)], False)
    )
    monkeypatch.setattr(explicit_ranking, "execute", execute)
    response, status = request(question)
    assert status == 200 and response["status"] == "success"
    assert response["model"] == "Aqua grouped ranking" and response["result_metadata"]
    query = execute.call_args.args[0].sql(dialect="postgres")
    expected = {"peers": "RANK()", "exact": "ROW_NUMBER()", "levels": "DENSE_RANK()"}
    assert expected[policy] in query and "ranked.position <= 2" in query
    assert ("COUNT(*)" if metric == "row count" else 'SUM("volume")') in query


@pytest.mark.parametrize(
    "question",
    [
        "Rank groups:",
        "Rank groups: Display the winners.",
        COMMAND.replace("From dispatch, ", ""),
        COMMAND.replace("dispatch", "unavailable"),
        COMMAND.replace("aisles", "private field"),
        COMMAND.replace("row count", "total aisle"),
        COMMAND.replace("2", "0"),
        COMMAND.replace("2", "1001"),
        COMMAND.replace(", including ties.", "."),
        COMMAND + " Return the aisle only.",
        COMMAND.replace("aisles", "aisles where the quantity exceeds 10"),
    ],
)
def test_unbound_explicit_requests_return_fixed_feedback(monkeypatch, question):
    monkeypatch.setattr(explicit_ranking, "execute", Mock(side_effect=AssertionError))
    result, code = request(question)
    assert code == 200
    assert result["status"] == "error"
    assert result["model"] == result["sql"] == ""
    assert result["tables"] == [] and "result_metadata" not in result
    assert result["error"] == {
        "code": "ranking_request_invalid",
        "message": "Start a new chat and use Rank groups with one source, one group field, and either row count or the total of one numeric field.",
        "retryable": False,
    }


def test_needs_first_owned_input_even_if_previous_turns_gave_no_context():
    blocked = Mock(side_effect=AssertionError("no schema access required"))
    for kwargs in ({"first_chat_input": False}, {"include_metadata": False}):
        assert (
            request(COMMAND, schema_reader=blocked, **kwargs)[0]["error"]["code"]
            == "ranking_request_invalid"
        )
    budget = Budget(time.monotonic() + 30, lambda _: None, [{"question": "history"}])
    token = CURRENT.set(budget)
    try:
        assert (
            request(COMMAND, schema_reader=blocked)[0]["error"]["code"]
            == "ranking_request_invalid"
        )
    finally:
        CURRENT.reset(token)


def test_plain_text_uses_the_selected_provider_path():
    plain = COMMAND.removeprefix(explicit_ranking.PREFIX)
    from nl2sql.pipeline import Answer

    ordinary = Mock(
        return_value=Answer(
            question=plain, sql="SELECT 1", columns=["n"], rows=[(1,)], model="fixture"
        )
    )
    factory = Mock(return_value=None)
    response, status = query_service.run(
        plain,
        "ollama",
        SETTINGS,
        "employee",
        5,
        2,
        first_chat_input=True,
        include_metadata=True,
        answerer=ordinary,
        schema_reader=lambda _: SCHEMA,
        retriever_factory=factory,
    )
    assert status == 200 and response["model"] == "fixture"
    assert ordinary.call_args.args[0] == plain and factory.call_count == 1


def test_public_row_budget_and_execution_failure_use_the_normal_worker(monkeypatch):
    execute = Mock(
        return_value=QueryResult("checked", ["aisle", "count"], [("A", 1)], True)
    )
    monkeypatch.setattr(explicit_ranking, "execute", execute)
    answer = explicit_ranking.answer_ranking(COMMAND, SETTINGS, SCHEMA, max_rows=1)
    assert answer.question == COMMAND and answer.truncated and answer.attempts == 0
    assert execute.call_args.kwargs["max_rows"] == 1
    execute.side_effect = QueryError("access_denied")
    response, _ = request(COMMAND)
    assert response["error"]["code"] == "access_denied" and response["model"] == ""
