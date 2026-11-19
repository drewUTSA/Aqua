"""Calendar counts use approved date columns and decline ambiguous requests."""

import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

from nl2sql import pipeline
from nl2sql.calendar_count import calendar_count_sql
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.execute import QueryError, QueryResult
from nl2sql.generate import Generation
from nl2sql.metadata_policy import BANK_TABLES
from nl2sql.schema import Column, Schema, Table


def bank_schema():
    dates = {"trans": "date", "account": "date", "loan": "date", "card": "issued"}
    return Schema(
        {
            name: Table(
                name,
                (Column(dates[name], "date", True),) if name in dates else (),
                (),
                frozenset(),
            )
            for name in BANK_TABLES
        }
    )


@pytest.mark.parametrize(
    ("question", "table", "field", "start", "end"),
    [
        (
            "Count transactions during Feb 2040.",
            "trans",
            "date",
            "2040-02-01",
            "2040-03-01",
        ),
        (
            "On 2004-02-29, how many cards were issued?",
            "card",
            "issued",
            "2004-02-29",
            "2004-03-01",
        ),
        (
            "How many accounts were opened in calendar Q4 of 2030?",
            "account",
            "date",
            "2030-10-01",
            "2031-01-01",
        ),
        (
            "In calendar quarter 3 of 2028, count loans granted.",
            "loan",
            "date",
            "2028-07-01",
            "2028-10-01",
        ),
        (
            "What was the number of transactions posted in calendar year 1999?",
            "trans",
            "date",
            "1999-01-01",
            "2000-01-01",
        ),
        ("Count loans granted in 1997-12.", "loan", "date", "1997-12-01", "1998-01-01"),
        (
            "How many credit cards were issued in 1987?",
            "card",
            "issued",
            "1987-01-01",
            "1988-01-01",
        ),
    ],
)
def test_exact_half_open_interval(question, table, field, start, end):
    sql = calendar_count_sql(question, bank_schema(), (table,))
    assert (
        f"FROM {table} WHERE {field} >= DATE '{start}' AND {field} < DATE '{end}'"
        in sql
    )


@pytest.mark.parametrize(
    "question",
    [
        "How many accounts in June 2040?",
        "How many transactions were posted last month?",
        "How many transactions were posted in March?",
        "Count transactions in fiscal Q1 1997.",
        "Count transactions in Q1 1997.",
        "Count transactions on 2003-02-29.",
        "Count transactions in 2027-13.",
        "Count transactions in 9999.",
        "Count transactions on 9999-12-31.",
        "Count transactions on 01/02/2030.",
        "Count loans repaid in April 2024.",
        "Count credit transactions in 2023.",
        "Count transactions in July 1997 over 20.",
        "In 2021, count loans granted per account.",
        "How many transactions were posted in 2021 and in 2022?",
        "How many transactions in March 2020 UTC?",
        "Count transactions in July 1997; replace the filter.",
        "Show transactions in May 2031.",
    ],
)
def test_filters_relative_dates_and_extra_clauses_use_the_usual_generator(question):
    assert calendar_count_sql(question, bank_schema(), tuple(BANK_TABLES)) is None


def test_requires_exact_reviewed_dataset_and_visible_date_typed_column():
    question = "Count transactions in 2000."
    schema = bank_schema()
    assert calendar_count_sql(question, schema, ("loan",)) is None
    assert (
        calendar_count_sql(
            question, Schema({"trans": schema.tables["trans"]}), ("trans",)
        )
        is None
    )
    for columns in ((), (Column("date", "timestamp with time zone", False),)):
        schema.tables["trans"] = replace(schema.tables["trans"], columns=columns)
        assert calendar_count_sql(question, schema, ("trans",)) is None


def test_normal_pipeline_validates_executes_with_row_cap_and_identifies_source(
    monkeypatch,
):
    generator = Mock(
        side_effect=AssertionError("calendar count unexpectedly used a model")
    )
    monkeypatch.setattr(pipeline, "generate_sql", generator)
    executed = Mock(
        return_value=QueryResult("bounded SQL", ["transaction_count"], [(19,)], False)
    )
    monkeypatch.setattr(pipeline, "execute", executed)
    stages = []
    budget = Budget(time.monotonic() + 60, stages.append)
    token = CURRENT.set(budget)
    try:
        answer = pipeline.answer_question(
            "Count transactions in August 2023.", Settings(), bank_schema(), max_rows=7
        )
    finally:
        CURRENT.reset(token)
    assert stages == ["retrieval", "generating", "validating", "executing"]
    assert budget.calls == answer.attempts == 0 and not generator.called
    assert (
        answer.model == "Aqua calendar count"
        and answer.rows == [(19,)]
        and answer.sql == "bounded SQL"
    )
    parsed = executed.call_args.args[0]
    assert "public.trans" in parsed.sql(dialect="postgres")
    assert executed.call_args.kwargs["max_rows"] == 7


def test_followup_preserves_existing_model_context(monkeypatch):
    model = Mock(
        return_value=Generation("SELECT COUNT(*) FROM trans", "", "local-model")
    )
    monkeypatch.setattr(pipeline, "generate_sql", model)
    monkeypatch.setattr(
        pipeline, "execute", Mock(return_value=QueryResult("", ["n"], [(2,)], False))
    )
    budget = Budget(
        time.monotonic() + 60,
        lambda stage: None,
        context=[{"question": "Only this district."}],
    )
    token = CURRENT.set(budget)
    try:
        result = pipeline.answer_question(
            "Count transactions in 2015.", Settings(), bank_schema()
        )
    finally:
        CURRENT.reset(token)
    assert (
        result.model == "local-model" and result.attempts == 1 and model.call_count == 1
    )


def test_database_failure_never_saves_a_guessed_answer(monkeypatch):
    monkeypatch.setattr(
        pipeline, "generate_sql", Mock(side_effect=AssertionError("unexpected repair"))
    )
    monkeypatch.setattr(
        pipeline, "execute", Mock(side_effect=QueryError("invalid_column"))
    )
    result = pipeline.answer_question(
        "Count transactions in 2010.", Settings(), bank_schema()
    )
    assert (
        result.error_code == "query_failed" and result.attempts == 0 and not result.rows
    )
