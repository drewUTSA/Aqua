"""Ordinary employee extrema require an actual, unambiguous parent/child key."""

from dataclasses import replace
from time import monotonic
from unittest.mock import Mock

import pytest

from nl2sql import pipeline
from nl2sql.config import Settings, load_settings
from nl2sql.control import Budget, CURRENT
from nl2sql.execute import QueryResult
from nl2sql.generate import Generation
from nl2sql.metadata_policy import BANK_TABLES, PAGILA_TABLES
from nl2sql.relationship_count import relationship_count_sql
from nl2sql.schema import Column, Schema, Table, get_schema
from nl2sql.validate import validate_sql


def catalog(manifest=BANK_TABLES, parent="district", child="account"):
    tables = {n: Table(n, (), (), frozenset()) for n in manifest}
    key = parent + "_id"
    tables[parent] = Table(
        parent,
        (Column(key, "integer", True),),
        (f'PRIMARY KEY ("{key}")',),
        frozenset(),
    )
    tables[child] = Table(
        child,
        (Column(key, "integer", False),),
        (f'FOREIGN KEY ("{key}") REFERENCES "{parent}"("{key}")',),
        frozenset({parent}),
    )
    return Schema(tables)


@pytest.mark.parametrize(
    ("question", "descending"),
    [
        ("What district has the fewest accounts?", False),
        ("Which districts have the smallest number of bank accounts?", False),
        (
            "Which district had the most account records, and how many did it have?",
            True,
        ),
        (
            "Which district had the largest number of accounts? Include any districts tied for first.",
            True,
        ),
        ("Please which district has the highest count of bank accounts?", True),
    ],
)
def test_single_proved_relationship_builds_a_population_wide_peer_cutoff(
    question, descending
):
    schema = catalog()
    sql = relationship_count_sql(question, schema, ("district", "account"))
    assert sql is not None
    valid = validate_sql(sql, allowed_tables=schema.allowed_tables).sql(
        dialect="postgres"
    )
    assert (
        "LEFT JOIN" in valid
        and "COUNT(c." in valid
        and "FETCH FIRST 1 ROWS WITH TIES" in valid
    )
    assert ("DESC FETCH" if descending else "ASC FETCH") in valid
    assert valid.endswith('ORDER BY winners."district_id" ASC')


@pytest.mark.parametrize(
    "question",
    [
        "List the busiest districts.",
        "Which district has at least one account?",
        "What district has the most active accounts?",
        "Which district had the fewest accounts in 2023?",
        "Which district had the fewest accounts? Include any customers tied for first.",
        "Which district has the fewest accounts? Return only its name.",
        "Which counterparty district has the most accounts?",
        "Which district has the highest account balance?",
        "Which district has the most accounts and customers?",
        "Which district has the most accounts per branch?",
        "Choose exactly one district with the most accounts.",
        "Which district had the most accounts? Exclude districts with no accounts.",
    ],
)
def test_unbound_roles_filters_outputs_and_counts_follow_the_existing_path(question):
    assert relationship_count_sql(question, catalog(), ("district", "account")) is None


def test_fk_proof_cannot_be_inferred_from_spelling_or_incomplete_retrieval():
    question = "Which district had the most accounts?"
    schema = catalog()
    for selected in [("district",), ("account",)]:
        assert relationship_count_sql(question, schema, selected) is None
    for constraints in [
        (),
        ('FOREIGN KEY ("alternate_id") REFERENCES "district"("district_id")',),
        (
            'FOREIGN KEY ("district_id") REFERENCES "district"("district_id")',
            'FOREIGN KEY ("previous_id") REFERENCES "district"("district_id")',
        ),
        (
            'FOREIGN KEY ("district_id", "year") REFERENCES "district"("district_id", "year")',
        ),
    ]:
        data = catalog()
        data.tables["account"] = replace(
            data.tables["account"], constraints=constraints
        )
        assert relationship_count_sql(question, data, tuple(data.tables)) is None
    for table, changes in [
        ("district", {"constraints": ()}),
        ("district", {"columns": ()}),
        ("account", {"columns": ()}),
        ("account", {"references": frozenset()}),
    ]:
        data = catalog()
        data.tables[table] = replace(data.tables[table], **changes)
        assert relationship_count_sql(question, data, tuple(data.tables)) is None


def employee(question, schema, settings, first=True, history=False, max_rows=4):
    budget = Budget(monotonic() + 10, lambda _: None, first_workspace_input=first)
    if history:
        budget.context = [{"question": "Earlier scope"}]
    token = CURRENT.set(budget)
    try:
        return pipeline.answer_question(question, settings, schema, max_rows=max_rows)
    finally:
        CURRENT.reset(token)


def test_normal_pipeline_preserves_worker_cap_and_followup_behavior(monkeypatch):
    question = "Which customer had the fewest rentals?"
    schema = catalog(PAGILA_TABLES, "customer", "rental")
    model = Mock(
        return_value=Generation(
            "SELECT customer_id FROM customer", "", "scripted provider"
        )
    )
    db = Mock(
        return_value=QueryResult(
            "", ["customer_id", "rental_count"], [(6, 0), (7, 0)], False
        )
    )
    monkeypatch.setattr(pipeline, "generate_sql", model)
    monkeypatch.setattr(pipeline, "execute", db)
    result = employee(question, schema, Settings())
    assert (
        result.model == "Aqua relationship count"
        and result.attempts == 0
        and result.size.kind == "single"
    )
    assert (
        result.rows == [(6, 0), (7, 0)]
        and not model.called
        and db.call_args.kwargs["max_rows"] == 4
    )
    for first, history, rules in [
        (False, False, True),
        (True, True, True),
        (True, False, False),
    ]:
        result = employee(
            question, schema, Settings(answer_size_rules=rules), first, history
        )
        assert result.attempts == 1 and result.model == "scripted provider"
    assert model.call_count == 3


def test_stock_reader_and_visible_live_foreign_keys(live_database, monkeypatch):
    settings = load_settings()
    schema = get_schema(settings)
    model = Mock(
        side_effect=AssertionError("relationship query unexpectedly used a provider")
    )
    monkeypatch.setattr(pipeline, "generate_sql", model)
    if live_database == "bank":
        question = "Which district has the largest number of bank accounts?"
        expected, fields = [(1, 1)], ["district_id", "account_count"]
    else:
        question = "Which customer has the fewest rentals?"
        expected, fields = [], ["customer_id", "rental_count"]
    answer = employee(question, schema, settings)
    assert answer.error is None and answer.model == "Aqua relationship count"
    assert (
        answer.rows == expected
        and answer.columns == fields
        and answer.attempts == 0
        and not model.called
    )
