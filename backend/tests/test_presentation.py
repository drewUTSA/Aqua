"""Exact reference results prove the bounded, declarative P08 workspace contract."""

import datetime as dt
from decimal import Decimal
import json
import time

import pytest

from nl2sql.config import Settings
from nl2sql.control import Budget, CURRENT
from nl2sql.pipeline import Answer
from nl2sql.presentation import presentation_for
from nl2sql.query_service import run
from nl2sql.response import to_response
from nl2sql.result_metadata import metadata_for
from nl2sql.schema import Column, Schema, Table
from nl2sql.visual_intent import intent_for

SOURCE = "a" * 64
SCHEMA = Schema(
    {
        "payments": Table(
            "payments",
            (Column("amount", "numeric", True, comment="Amount in dollars (USD)."),),
            (),
            frozenset(),
            comment="Synthetic payments.",
        )
    }
)


def present(
    columns,
    rows,
    *,
    question="Show a chart",
    sql="SELECT approved",
    context=(),
    schema=None,
):
    answer = Answer(question, sql, columns=columns, rows=rows)
    response = to_response(answer)
    metadata = metadata_for(answer, source_id=SOURCE)
    return presentation_for(answer, response, metadata, context=context, schema=schema)


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("How many films?", "text"),
        ("Graph monthly revenue", "explicit"),
        ("Show a bar chart", "explicit"),
        ("Explain this chart", "text"),
        ("Can you explain the chart?", "text"),
        ("Please explain this chart", "text"),
        ("Could you please describe the graph?", "text"),
        ("Please can you tell me about this plot?", "text"),
        ("Do not show me a chart", "text"),
        ("Please don't show us any graphs", "text"),
        ("I do not want to show a chart", "text"),
        ("Could you not show me the plot?", "text"),
        ("Can you show a chart?", "explicit"),
        ("Please could you plot revenue by month?", "explicit"),
        ("No refunds were paid; show a chart", "explicit"),
        ("No chart, just the total", "text"),
        ("Show the table without a chart", "text"),
        ("A photograph of a graphologist", "text"),
    ],
)
def test_visual_intent_is_task_specific(question, expected):
    assert intent_for(question) == expected


def test_followup_inheritance_is_narrow_and_interrupted_by_unrelated_text():
    context = [
        {"question": "Plot revenue by month"},
        {"question": "Now only last year"},
    ]
    assert intent_for("And group by quarter", context) == "followup"
    assert intent_for("Explain the result", context) == "text"
    assert intent_for("Also how are you", context) == "text"
    assert (
        intent_for("Now only last year", [*context, {"question": "What is revenue?"}])
        == "text"
    )
    assert intent_for("Could you now only show last year?", context) == "followup"
    for question in (
        "Can you explain the chart?",
        "Please explain this chart",
        "Do not show me a chart",
    ):
        assert intent_for(question, context) == "text"
        assert (
            intent_for("Now only last year", [*context, {"question": question}])
            == "text"
        )
        result = present(
            ["name", "count"], [("A", 1), ("B", 2)], question=question, context=context
        )
        assert result["default_view"] == "summary"
        assert result["charts"] == []


def test_plain_answer_does_not_open_a_visual_even_if_legacy_shape_suggests_a_bar():
    result = present(
        ["name", "count"], [("A", 1), ("B", 2)], question="How many per name?"
    )
    assert result == {
        "version": 1,
        "intent": "text",
        "default_view": "summary",
        "reason": "ordinary_text",
        "charts": [],
    }


def test_compound_categories_and_missing_negative_zero_values_keep_exact_rows():
    result = present(
        ["first", "last", "amount"],
        [("A B", "C", Decimal("-10.25")), ("A", "B C", 0), ("D", "E", None)],
    )
    (chart,) = result["charts"]
    assert chart["x"] == {
        "keys": ["first", "last"],
        "kind": "category",
        "timezone": None,
        "calendar_parts": [],
    }
    assert chart["row_indices"] == [0, 1, 2]
    assert chart["series"] == [{"key": "amount", "label": "Amount", "unit": None}]
    assert chart["input_rows"] == chart["output_points"] == 3
    assert chart["missing"] == "gap" and chart["reduction"] == "none"
    assert not chart["downsampled"] and not chart["approximate"]
    assert set(chart) == {
        "id",
        "type",
        "title",
        "tableId",
        "x",
        "series",
        "row_indices",
        "missing",
        "reduction",
        "input_rows",
        "output_points",
        "downsampled",
        "compatibility_key",
        "approximate",
    }


def test_compound_calendar_axis_is_ordered_without_losing_the_year():
    (chart,) = present(["year", "month", "n"], [(2023, 1, 3), (2022, 12, 4)])["charts"]
    assert chart["type"] == "line" and chart["row_indices"] == [1, 0]
    assert chart["x"] == {
        "keys": ["year", "month"],
        "kind": "calendar",
        "timezone": None,
        "calendar_parts": ["year", "month"],
    }


def test_aware_instants_are_utc_sorted_while_dates_keep_calendar_semantics():
    offset = dt.timezone(dt.timedelta(hours=-6))
    rows = [
        (dt.datetime(2026, 1, 1, 3, tzinfo=dt.timezone.utc), 3),
        (dt.datetime(2025, 12, 31, 20, tzinfo=offset), 2),
    ]
    (chart,) = present(["time", "n"], rows)["charts"]
    assert chart["x"]["timezone"] == "UTC" and chart["row_indices"] == [1, 0]
    (date,) = present(
        ["day_start", "n"], [(dt.date(2026, 1, 2), 1), (dt.date(2026, 1, 1), 2)]
    )["charts"]
    assert date["x"]["kind"] == "date" and date["x"]["timezone"] is None


@pytest.mark.parametrize(
    "rows",
    [
        [(dt.datetime(2026, 1, 1), 1), (dt.datetime(2026, 1, 2), 2)],
        [
            (dt.datetime(2026, 1, 1, microsecond=1, tzinfo=dt.timezone.utc), 1),
            (dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc), 2),
        ],
        [(dt.date(2026, 1, 1), 1), (None, 2)],
        [
            (dt.datetime(2026, 1, 1, tzinfo=dt.timezone(dt.timedelta(seconds=30))), 1),
            (dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc), 2),
        ],
    ],
)
def test_unspecified_or_unrepresentable_time_axes_fall_back_to_table(rows):
    result = present(["date", "n"], rows)
    assert result["charts"] == [] and result["reason"] == "invalid_axis"


@pytest.mark.parametrize(
    ("count", "kind", "expected"),
    [
        (50, "bar", "chart"),
        (51, "bar", "table"),
        (500, "line", "chart"),
        (501, "line", "table"),
    ],
)
def test_point_and_category_caps_do_not_sample_or_change_totals(count, kind, expected):
    labels = [
        str(index) if kind == "bar" else dt.date(2020, 1, 1) + dt.timedelta(days=index)
        for index in range(count)
    ]
    result = present(
        ["label", "n"], [(label, index) for index, label in enumerate(labels)]
    )
    assert result["default_view"] == expected
    if expected == "table":
        assert result["reason"] == "point_limit" and not result["charts"]
    else:
        assert len(result["charts"][0]["row_indices"]) == count


def test_two_series_require_proven_compatible_units_and_share_the_point_budget():
    rows = [
        (dt.date(2020, 1, 1) + dt.timedelta(days=index), index, index * 2)
        for index in range(250)
    ]
    sql = "SELECT day, COUNT(*), COUNT(amount) FROM payments GROUP BY day"
    result = present(["day", "all_count", "amount_count"], rows, sql=sql, schema=SCHEMA)
    (chart,) = result["charts"]
    assert [series["unit"] for series in chart["series"]] == ["count", "count"]
    assert chart["output_points"] == 500
    assert (
        present(
            ["day", "all_count", "amount_count"],
            rows + [(dt.date(2021, 1, 1), 1, 2)],
            sql=sql,
            schema=SCHEMA,
        )["reason"]
        == "point_limit"
    )
    assert (
        present(["name", "rentals", "revenue"], [("A", 1, 2), ("B", 3, 4)])["reason"]
        == "ambiguous_units"
    )


def test_currency_requires_source_documentation_instead_of_an_alias_guess():
    sql = "SELECT name, SUM(amount) AS revenue FROM payments GROUP BY name"
    (chart,) = present(
        ["name", "revenue"],
        [("A", Decimal("10.25")), ("B", Decimal("0.10"))],
        sql=sql,
        schema=SCHEMA,
    )["charts"]
    assert chart["series"][0]["unit"] == "USD"
    (chart,) = present(["name", "revenue"], [("A", 1), ("B", 2)])["charts"]
    assert chart["series"][0]["unit"] is None


def test_any_exact_sidecar_cell_keeps_the_whole_result_table_only():
    result = present(
        ["record_id", "name", "amount"],
        [(9007199254740993, "A", 1), (9007199254740995, "B", 2)],
    )
    assert result["reason"] == "precision_limit" and result["charts"] == []
    assert (
        present(
            ["name", "amount"], [("A", Decimal("0.1234567890123456789")), ("B", 2)]
        )["reason"]
        == "precision_limit"
    )


def test_unsafe_integer_geometry_from_a_float_is_not_offered_to_the_renderer():
    result = present(["name", "value"], [("A", 9007199254740994.0), ("B", 2.0)])
    assert result["charts"] == [] and result["default_view"] == "table"


def test_zoom_compatibility_changes_with_period_source_or_units_but_not_measure_values():
    first = present(["name", "n"], [("A", 1), ("B", 2)])["charts"][0][
        "compatibility_key"
    ]
    assert (
        present(["name", "n"], [("A", 3), ("B", 4)])["charts"][0]["compatibility_key"]
        == first
    )
    assert (
        present(["name", "n"], [("C", 1), ("D", 2)])["charts"][0]["compatibility_key"]
        != first
    )
    assert (
        present(
            ["name", "n"], [("A", 1), ("B", 2)], sql="SELECT approved WHERE year=2025"
        )["charts"][0]["compatibility_key"]
        != first
    )


def test_workspace_extension_preserves_legacy_shape_metadata_and_context_contract():
    answer = Answer(
        "Now only last year",
        "SELECT name,n FROM approved",
        columns=["name", "n"],
        rows=[("A", 1), ("B", 2)],
    )
    budget = Budget(
        time.monotonic() + 10, lambda stage: None, [{"question": "Plot counts by name"}]
    )
    token = CURRENT.set(budget)
    try:
        args = dict(
            schema_reader=lambda settings: Schema({}),
            answerer=lambda *args, **kwargs: answer,
            retriever_factory=lambda settings: None,
        )
        legacy, code = run(
            answer.question, "ollama", Settings(retrieval=False), "owner", 1, 0, **args
        )
        workspace, workspace_code = run(
            answer.question,
            "ollama",
            Settings(retrieval=False),
            "owner",
            1,
            0,
            include_metadata=True,
            **args,
        )
    finally:
        CURRENT.reset(token)
    assert code == workspace_code == 200
    assert set(legacy) == {
        "status",
        "sql",
        "model",
        "message",
        "tables",
        "visualizations",
        "kpis",
        "error",
    }
    assert {key: workspace[key] for key in legacy} == legacy
    assert (
        workspace["presentation"]["intent"] == "followup"
        and workspace["presentation"]["default_view"] == "chart"
    )
    assert set(workspace["result_metadata"]) == {
        "version",
        "source",
        "generated_at",
        "filters",
        "truncated",
        "max_rows",
        "aggregation",
        "column_units",
        "exact_values",
    }
    assert workspace["result_metadata"]["source"]["freshness_at"] is None
    assert workspace["result_metadata"]["aggregation"] == "unknown"
    json.dumps(workspace, allow_nan=False)
