"""Independent grouped-rank contract on fictional calibration records."""

from dataclasses import replace
import sqlite3
import time
from unittest.mock import Mock

import pytest

from nl2sql import pipeline
from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.execute import QueryResult
from nl2sql.generate import Generation
from nl2sql.grouped_rank import grouped_rank_sql
from nl2sql.schema import Column, Schema, Table
from nl2sql.validate import validate_sql


def table(name, *columns):
    return Table(name, tuple(columns), (), frozenset())


BENCH = Column("bench", "text", True)
DRIFT = Column("drift", "integer", True)
FACT = table("calibration", BENCH, DRIFT, Column("inspector_id", "integer", True))
SCHEMA = Schema({FACT.name: FACT})
DATA = [
    ("A", 4, 1),
    ("A", 4, 1),
    ("B", 8, 1),
    ("C", 5, 2),
    ("D", 3, 2),
    ("D", 2, 3),
    ("E", -2, 2),
]
CASES = [
    (
        "Which benches had the most calibrations?",
        ["bench", "calibration_count"],
        [("A", 2), ("D", 2)],
    ),
    (
        "Show all benches tied for the highest total drift from calibrations.",
        ["bench", "total_drift"],
        [("A", 8), ("B", 8)],
    ),
    (
        "From calibrations, show the top three benches by total drift, including ties.",
        ["bench", "total_drift"],
        [("A", 8), ("B", 8), ("C", 5), ("D", 5)],
    ),
    (
        "Which benches have the top two distinct total drift values from calibrations? Return rank and bench.",
        ["rank", "bench"],
        [(1, "A"), (1, "B"), (2, "C"), (2, "D")],
    ),
    (
        "From calibrations, give the top two benches by total drift, including ties. Return bench only.",
        ["bench"],
        [("A",), ("B",)],
    ),
    (
        "From calibrations, show exactly the bottom two benches by number of records. Break ties by bench descending.",
        ["bench", "calibration_count"],
        [("E", 1), ("C", 1)],
    ),
    (
        "Group calibrations by bench and show the top three groups by total drift, including ties. Within each tie, order by bench descending.",
        ["bench", "total_drift"],
        [("B", 8), ("A", 8), ("D", 5), ("C", 5)],
    ),
    (
        "Give the two lowest benches by total drift. Return total drift and bench. Order by bench descending.",
        ["total_drift", "bench"],
        [(-2, "E"), (5, "C")],
    ),
    (
        "From calibrations, show the bottom two inspector IDs by calibration count.",
        ["inspector_id", "calibration_count"],
        [(3, 1), (1, 3)],
    ),
]


@pytest.mark.parametrize(("question", "columns", "expected"), CASES)
def test_membership_order_and_only_requested_fields(question, columns, expected):
    sql = grouped_rank_sql(question, SCHEMA, ("calibration",))
    assert sql is not None
    validate_sql(sql, allowed_tables=SCHEMA.allowed_tables)
    with sqlite3.connect(":memory:") as db:
        db.execute("ATTACH ':memory:' AS public")
        db.execute(
            "CREATE TABLE public.calibration(bench TEXT, drift INTEGER, inspector_id INTEGER)"
        )
        db.executemany("INSERT INTO public.calibration VALUES (?,?,?)", DATA)
        result = db.execute(sql)
        assert [field[0] for field in result.description] == columns
        assert result.fetchall() == expected


@pytest.mark.parametrize(
    "question",
    [
        "Show every bench's total drift and mark the top two, including ties.",
        "From calibrations, show all benches by total drift.",
        "From calibrations, show the top two benches by total drift since Monday.",
        "From calibrations, show the top two benches by total drift where drift exceeds zero.",
        "Which benches have one of the highest total drift values?",
        "Which benches had the most drift?",
        "Which benches had the highest average drift?",
        "Show the top two benches by total drift and calibration count.",
        "Show the top two benches per inspector by total drift.",
        "Show the top two benches by total drift. Display bench and inspector identifier.",
        "Show exactly the top two benches by total drift, including ties.",
        "Show the top two benches by total drift, including ties. Break ties by bench ascending.",
        "Show the top two benches by total drift. Order by calibration count descending.",
        "Show the top 1001 benches by total drift.",
        "Show the top two benches by total drift from calibrations and inspections.",
        "Show the top two benches by total distinct drift.",
        "From calibrations, show the top two benches by total drift. Display rank.",
        "Show the bottom two inspectors by calibration count.",
    ],
)
def test_unconsumed_or_unsupported_semantics_use_model(question):
    assert grouped_rank_sql(question, SCHEMA, ("calibration",)) is None


def test_schema_scope_and_ambiguity_are_independent_of_retrieval():
    other = replace(FACT, name="inspection")
    schema = Schema({"calibration": FACT, "inspection": other})
    basic = "Show the top two benches by total drift."
    assert grouped_rank_sql(basic, schema, ("calibration",)) is None
    assert (
        grouped_rank_sql("From inspections, " + basic.lower(), schema, ("calibration",))
        is None
    )
    assert grouped_rank_sql(
        "From calibrations, " + basic.lower(), schema, ("calibration",)
    )
    for col in (
        replace(DRIFT, not_null=False),
        replace(DRIFT, type="text"),
        replace(BENCH, not_null=False),
    ):
        columns = [
            col if original.name == col.name else original for original in FACT.columns
        ]
        assert (
            grouped_rank_sql(
                basic,
                Schema({"calibration": table("calibration", *columns)}),
                ("calibration",),
            )
            is None
        )
    overlapping = table(
        "calibration", BENCH, Column("bench_id", "integer", True), DRIFT
    )
    assert (
        grouped_rank_sql(basic, Schema({"calibration": overlapping}), ("calibration",))
        is None
    )
    assert grouped_rank_sql(
        "From calibrations, show the top two bench IDs by total drift.",
        Schema({"calibration": overlapping}),
        ("calibration",),
    )


def test_group_output_named_score_does_not_replace_aggregate_display_order():
    schema = Schema(
        {"calibration": table("calibration", replace(BENCH, name="score"), DRIFT)}
    )
    query = grouped_rank_sql(
        "From calibrations, show the top two scores by total drift.",
        schema,
        ("calibration",),
    )
    with sqlite3.connect(":memory:") as db:
        db.execute("ATTACH ':memory:' AS public")
        db.execute("CREATE TABLE public.calibration(score TEXT, drift INTEGER)")
        db.executemany(
            "INSERT INTO public.calibration VALUES (?,?)", [("Y", 2), ("A", 8)]
        )
        assert db.execute(query).fetchall() == [("A", 8), ("Y", 2)]


def test_only_visible_compatible_non_null_metrics_and_units_can_be_summed():
    for name, metric, columns in [
        ("staff", "password", [BENCH, Column("password", "integer", True)]),
        ("calibration", "inspector IDs", list(FACT.columns)),
        ("calibration", "drift", [*FACT.columns, Column("unit_code", "text", True)]),
    ]:
        schema = Schema({name: table(name, *columns)})
        question = f"From {name}, show the top two benches by total {metric}."
        assert grouped_rank_sql(question, schema, (name,)) is None
    typed = table(
        "calibration",
        replace(BENCH, type="character varying(12)"),
        replace(DRIFT, type="numeric(9,2)"),
    )
    assert grouped_rank_sql(
        "From calibrations, show the top two benches by total drift.",
        Schema({"calibration": typed}),
        ("calibration",),
    )


def test_ordinary_entry_validates_sql_keeps_row_budget_and_uses_the_right_source(
    monkeypatch,
):
    provider = Mock(
        return_value=Generation(
            "SELECT bench FROM calibration", thinking="", model="dev-model"
        )
    )
    checked = Mock(wraps=validate_sql)
    executor = Mock(return_value=QueryResult("checked", ["bench"], [("A",)], True))
    monkeypatch.setattr(pipeline, "generate_sql", provider)
    monkeypatch.setattr(pipeline, "validate_sql", checked)
    monkeypatch.setattr(pipeline, "execute", executor)
    question = CASES[0][0]
    answer = pipeline.answer_question(question, Settings(), SCHEMA, max_rows=1)
    assert (answer.model, answer.attempts, answer.truncated) == (
        "Aqua grouped ranking",
        0,
        True,
    )
    provider.assert_not_called()
    assert checked.call_args.kwargs["allowed_tables"] == SCHEMA.allowed_tables
    assert executor.call_args.kwargs["max_rows"] == 1
    assert (
        pipeline.answer_question(
            question, replace(Settings(), answer_size_rules=False), SCHEMA
        ).model
        == "dev-model"
    )
    budget = Budget(
        time.monotonic() + 30, lambda _: None, context=(("previous", "answer"),)
    )
    token = CURRENT.set(budget)
    try:
        assert (
            pipeline.answer_question(question, Settings(), SCHEMA).model == "dev-model"
        )
    finally:
        CURRENT.reset(token)
    assert provider.call_count == 2
