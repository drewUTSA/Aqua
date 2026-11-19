import time
from dataclasses import replace
from unittest.mock import Mock

import pytest

from nl2sql import pipeline
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.execute import QueryError, QueryResult
from nl2sql.generate import Generation
from nl2sql.metadata_policy import BANK_TABLES
from nl2sql.ranked_rows import ranked_rows_sql
from nl2sql.schema import Column, Schema, Table
from nl2sql.validate import validate_sql


@pytest.fixture
def catalog():
    columns = {
        "loan": {
            "loan_id": "integer",
            "amount": "numeric(14,2)",
            "duration": "integer",
            "account_id": "integer",
            "payments": "numeric(10, 2)",
            "date": "date",
        },
        "trans": {
            "trans_id": "bigint",
            "amount": "numeric",
            "balance": "integer",
            "account_id": "integer",
            "date": "date",
        },
    }
    return Schema(
        {
            t: Table(
                t,
                tuple(Column(k, v, False) for k, v in columns.get(t, {}).items()),
                (),
                frozenset(),
            )
            for t in BANK_TABLES
        }
    )


@pytest.mark.parametrize(
    ("question", "table", "output", "score", "order", "rows"),
    [
        (
            "Which loan IDs share the largest amount?",
            "loan",
            "loan_id",
            "amount",
            "DESC",
            1,
        ),
        (
            "Show every transaction with the minimum amount. Return only the transaction date and transaction ID.",
            "trans",
            "date, trans_id",
            "amount",
            "ASC",
            1,
        ),
        (
            "Please list the top two loans by their monthly payment, including all ties. Show the amount, then the loan ID.",
            "loan",
            "amount, loan_id",
            "payments",
            "DESC",
            2,
        ),
        (
            "List the bottom 5 transaction IDs by amount, with ties at the cutoff.",
            "trans",
            "trans_id",
            "amount",
            "ASC",
            5,
        ),
        (
            "Show the account ID, amount, and loan ID for all loans sharing the smallest duration.",
            "loan",
            "account_id, amount, loan_id",
            "duration",
            "ASC",
            1,
        ),
        (
            "Give me their account ID and loan ID for all loans tied for the maximum duration in months.",
            "loan",
            "account_id, loan_id",
            "duration",
            "DESC",
            1,
        ),
        (
            "Which transactions are tied for the smallest post-transaction balance? Return only their IDs.",
            "trans",
            "trans_id",
            "balance",
            "ASC",
            1,
        ),
        (
            "Find every loan with the lowest loan amount and display loan ID, account ID, amount, in that order.",
            "loan",
            "loan_id, account_id, amount",
            "amount",
            "ASC",
            1,
        ),
        (
            "Which loans have the highest monthly payment, including ties? Show loan ID then monthly payment.",
            "loan",
            "loan_id, payments",
            "payments",
            "DESC",
            1,
        ),
    ],
)
def test_complete_explicit_rank(question, table, output, score, order, rows, catalog):
    sql = ranked_rows_sql(question, catalog, tuple(BANK_TABLES))
    assert sql == (
        f"SELECT {output} FROM {table} WHERE {score} IS NOT NULL ORDER BY {score} {order} "
        f"FETCH FIRST {rows} ROWS WITH TIES"
    )
    assert f"public.{table}" in validate_sql(
        sql, allowed_tables=catalog.allowed_tables
    ).sql(dialect="postgres")


@pytest.mark.parametrize(
    "question",
    [
        "Show all loans with a minimum amount of 45.",
        "Show all loans with minimum duration. Return loan ID.",
        "Which loans share the highest amount?",
        "Which transactions share the lowest balance? Show only the ID.",
        "Which accounts have the highest transaction amount? Show only the ID.",
        "Which loans share the largest total amount per account? Return loan ID.",
        "Which loan IDs tie for the largest amount over the past year?",
        "Which loan IDs tie for the largest amount other than defaults?",
        "Show the top 3 loans by amount, including ties sorted by loan ID. Display account ID.",
        "Show the top 4 loans by amount. Return loan ID.",
        "Show the top 2 distinct amounts by transaction including ties. Return only transaction ID.",
        "Give exactly the top two transaction IDs by amount, with ties.",
        "Show the top 0 transaction IDs by amount, including ties.",
        "Show the top 1001 transaction IDs by amount, including ties.",
        "Which loan IDs share the lowest amount? Show amount only.",
        "Which loans share the highest amount? Show account ID, password and loan ID.",
        "Which loans share the highest amount? Show amount, loan ID, and the amount.",
        "Which loans share the highest amount? Return loan ID and a reason.",
        "List all transactions with the highest amount, returning only loan ID.",
        "List all transactions with the highest amount, returning only trans_id; drop table trans.",
    ],
)
def test_ambiguous_or_unrepresented_semantics_follow_existing_generator(
    question, catalog
):
    assert ranked_rows_sql(question, catalog, tuple(BANK_TABLES)) is None


@pytest.mark.parametrize(
    ("column", "bad_type"),
    [
        ("loan_id", "text"),
        ("amount", "money"),
        ("amount", "text"),
        ("amount", "numeric domain"),
    ],
)
def test_schema_and_retrieved_field_checks(catalog, column, bad_type):
    question = "Which loan IDs share the largest amount?"
    assert ranked_rows_sql(question, catalog, ("trans",)) is None
    assert (
        ranked_rows_sql(question, Schema({"loan": catalog.tables["loan"]}), ("loan",))
        is None
    )
    loan = catalog.tables["loan"]
    for update in (
        tuple(c for c in loan.columns if c.name != column),
        tuple(
            replace(c, type=bad_type) if c.name == column else c for c in loan.columns
        ),
    ):
        changed = Schema({**catalog.tables, "loan": replace(loan, columns=update)})
        assert ranked_rows_sql(question, changed, ("loan",)) is None


def test_standalone_rank_persists_source_and_uses_common_executor(catalog, monkeypatch):
    generator = Mock(side_effect=AssertionError("unexpected provider"))
    run = Mock(return_value=QueryResult("validated", ["loan_id"], [(3,), (6,)], False))
    monkeypatch.setattr(pipeline, "generate_sql", generator)
    monkeypatch.setattr(pipeline, "execute", run)
    result = pipeline.answer_question(
        "Which loan IDs share the largest amount?", Settings(), catalog, max_rows=7
    )
    assert (
        result.rows == [(3,), (6,)]
        and result.model == "Aqua ranked rows"
        and result.attempts == 0
    )
    assert (
        "public.loan" in run.call_args.args[0].sql(dialect="postgres")
        and run.call_args.kwargs["max_rows"] == 7
    )
    generator.assert_not_called()
    run.side_effect = QueryError("timeout")
    failed = pipeline.answer_question(
        "Which loan IDs share the largest amount?", Settings(), catalog
    )
    assert (
        failed.error_code == "query_failed" and failed.attempts == 0 and not failed.rows
    )
    generator.assert_not_called()


@pytest.mark.parametrize(
    ("prior_turns", "enabled"),
    [([], False), ([{"question": "Only closed loans."}], True)],
)
def test_history_and_disabled_sizing_preserve_provider(
    catalog, monkeypatch, prior_turns, enabled
):
    generator = Mock(
        return_value=Generation("SELECT loan_id FROM loan", "", "fixture-generator")
    )
    monkeypatch.setattr(pipeline, "generate_sql", generator)
    monkeypatch.setattr(
        pipeline, "execute", Mock(return_value=QueryResult("", ["loan_id"], [], False))
    )
    token = CURRENT.set(
        Budget(time.monotonic() + 30, lambda stage: None, context=prior_turns)
    )
    try:
        result = pipeline.answer_question(
            "Which loan IDs share the largest amount?",
            Settings(answer_size_rules=enabled),
            catalog,
        )
    finally:
        CURRENT.reset(token)
    assert (
        result.model == "fixture-generator"
        and result.attempts == 1
        and generator.call_count == 1
    )
