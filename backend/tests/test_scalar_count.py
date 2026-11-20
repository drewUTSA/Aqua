"""Ordinary counts bind only one reviewed entity and a complete optional predicate."""

from dataclasses import replace
import time
from unittest.mock import Mock

import pytest

from nl2sql import pipeline
from nl2sql.config import Settings, load_settings
from nl2sql.control import Budget, CURRENT
from nl2sql.execute import QueryError, QueryResult
from nl2sql.generate import Generation
from nl2sql.metadata_policy import BANK_TABLES, PAGILA_TABLES
from nl2sql.scalar_count import scalar_count_sql
from nl2sql.schema import Column, Schema, Table, get_schema
from nl2sql.validate import validate_sql


def catalog(relations=BANK_TABLES):
    return Schema(
        {
            table: Table(
                table,
                (
                    Column(f"{table}_id", "integer", True),
                    Column("amount", "integer", False),
                ),
                (),
                frozenset(),
            )
            for table in relations
        }
    )


@pytest.mark.parametrize(
    ("relations", "question", "table", "predicate"),
    [
        (BANK_TABLES, "How many customers are there?", "client", ""),
        (PAGILA_TABLES, "How many customers are there?", "customer", ""),
        (BANK_TABLES, "Count all standing orders.", "order", ""),
        (PAGILA_TABLES, "Please show me the total number of films.", "film", ""),
        (
            BANK_TABLES,
            "How many loan records have an amount greater than 280.75?",
            "loan",
            " > 280.75",
        ),
        (
            BANK_TABLES,
            "How many transactions are there with an amount under 91 CZK?",
            "trans",
            " < 91",
        ),
        (
            BANK_TABLES,
            "Count transactions whose amount is at least 482.",
            "trans",
            " >= 482",
        ),
        (
            BANK_TABLES,
            "Count transactions where the amount is at most -2.",
            "trans",
            " <= -2",
        ),
        (
            PAGILA_TABLES,
            "How many payments with amount exactly 8.125?",
            "payment",
            " = 8.125",
        ),
    ],
)
def test_count_and_each_comparator(relations, question, table, predicate):
    sql = scalar_count_sql(question, catalog(relations), (table,))
    expected = f'SELECT COUNT(*) AS record_count FROM "{table}"'
    assert sql == expected + (" WHERE amount" + predicate if predicate else "")
    assert validate_sql(sql, allowed_tables={table}) is not None


@pytest.mark.parametrize(
    "question",
    [
        "How many account owners are there?",
        "Count transactions above the average.",
        "Count transactions with an amount over 9 USD.",
        "Count clients with amount above 5.",
        "Count transactions with amount over 1,250.",
        "Count transactions with amount over 1e2.",
        "Count transactions with amount over 20 per client.",
        "Count transactions with amount over 20 or under 5.",
        "Count transactions with amount above 20; list dates too.",
        "Count loan records with amount under 1.0000001.",
        "Count the distinct transactions from the previous question.",
        "Count active loans.",
        "Count customers again.",
        "Count transactions over 15 years.",
        "Show transactions with an amount over 8.",
        "Rank the three largest transactions including ties.",
    ],
)
def test_other_intents_and_units_defer(question):
    assert scalar_count_sql(question, catalog(), tuple(BANK_TABLES)) is None


def test_schema_scope_visible_id_and_numeric_measure_are_required():
    question = "Count transactions where amount is over 80."
    schema = catalog()
    assert scalar_count_sql(question, schema, ("account",)) is None
    assert scalar_count_sql(question, catalog({"trans"}), ("trans",)) is None
    for columns in [
        (Column("amount", "integer", False),),
        (Column("trans_id", "integer", True),),
        (Column("trans_id", "integer", True), Column("amount", "text", True)),
    ]:
        schema.tables["trans"] = replace(schema.tables["trans"], columns=columns)
        assert scalar_count_sql(question, schema, ("trans",)) is None
    assert (
        scalar_count_sql(
            "Count payments with amount over 8 CZK.",
            catalog(PAGILA_TABLES),
            ("payment",),
        )
        is None
    )


def test_frozen_history_defers_and_database_errors_do_not_retry(monkeypatch):
    query = "How many bank accounts are there?"
    model = Mock(
        return_value=Generation("SELECT COUNT(*) FROM account", "", "ordinary model")
    )
    monkeypatch.setattr(pipeline, "generate_sql", model)
    monkeypatch.setattr(
        pipeline, "execute", Mock(return_value=QueryResult("", ["n"], [(2,)], False))
    )
    token = CURRENT.set(
        Budget(
            time.monotonic() + 30,
            lambda _: None,
            context=[{"question": "Only my district"}],
        )
    )
    try:
        answer = pipeline.answer_question(query, Settings(), catalog())
    finally:
        CURRENT.reset(token)
    assert model.call_count == answer.attempts == 1 and answer.model == "ordinary model"
    model.reset_mock()
    execute = Mock(side_effect=QueryError("invalid_column"))
    monkeypatch.setattr(pipeline, "execute", execute)
    answer = pipeline.answer_question(query, Settings(), catalog(), max_rows=4)
    assert answer.attempts == 0 and answer.model == "Aqua record count"
    assert not model.called and execute.call_args.kwargs["max_rows"] == 4
    assert answer.error_code == "query_failed" and not answer.rows


def test_stock_reader_returns_exact_answer_without_generation(
    live_database, monkeypatch
):
    settings = load_settings()
    question, expected = (
        ("Count transactions with amount at most 37.50 CZK.", 37)
        if live_database == "bank"
        else ("How many films are there?", 1000)
    )
    model = Mock(side_effect=AssertionError("scalar count used the model"))
    monkeypatch.setattr(pipeline, "generate_sql", model)
    result = pipeline.answer_question(
        question, settings, get_schema(settings), max_rows=1
    )
    assert (
        not result.error
        and result.rows == [(expected,)]
        and result.columns == ["record_count"]
    )
    assert (
        result.model == "Aqua record count"
        and result.attempts == 0
        and not model.called
    )
