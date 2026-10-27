"""Independent chart safety and exact-data references; no providers or SQL run."""

from copy import deepcopy
import datetime as dt
from decimal import Decimal
import json

import pytest

from nl2sql.pipeline import Answer
from nl2sql.presentation import presentation_for
from nl2sql.response import to_response
from nl2sql.result_metadata import metadata_for
from nl2sql.visual_intent import intent_for


def render(columns, rows, *, question="Show a chart", sql="SELECT approved", **extra):
    answer = Answer(question, sql, columns=columns, rows=rows, **extra)
    response = to_response(answer)
    metadata = metadata_for(answer, source_id="a" * 64)
    return presentation_for(answer, response, metadata), response, metadata


def table_only(presentation, reason):
    assert presentation["default_view"] == "table"
    assert presentation["charts"] == [] and presentation["reason"] == reason


@pytest.mark.parametrize("question", ["What is a graph?", "Explain this chart"])
def test_ordinary_explanations_do_not_open_a_visual_or_inherit_one(question):
    context = [{"question": "Show a chart of counts by category"}]
    assert intent_for(question, context) == "text"
    assert intent_for("Graph counts by category", context) == "explicit"


def test_untrusted_previous_chart_options_cannot_enter_new_closed_configuration():
    answer = Answer(
        "Chart <img src=https://outside.invalid/track>",
        "SELECT approved",
        columns=["label", "amount"],
        rows=[("A", 2), ("B", 1)],
    )
    response = to_response(answer)
    metadata = metadata_for(answer, source_id="a" * 64)
    clean = presentation_for(answer, response, metadata)
    response["visualizations"] = [
        {
            "type": "scattergl",
            "layout": {"images": [{"source": "https://outside.invalid/track"}]},
            "config": {"showSendToCloud": True},
            "hovertemplate": "<script>PRIVATE()</script>",
        }
    ]
    response["presentation"] = {"version": 999, "charts": [{"javascript": "PRIVATE()"}]}
    before = deepcopy((answer, response, metadata))
    result = presentation_for(answer, response, metadata)
    assert result == clean and (answer, response, metadata) == before
    (chart,) = result["charts"]
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
    assert chart["type"] == "bar" and chart["tableId"] == "result"
    assert len(chart["title"]) <= 160


@pytest.mark.parametrize("reserved", ["__proto__", "constructor", "prototype"])
def test_reserved_source_aliases_remain_table_data_but_never_become_configuration(
    reserved,
):
    result, response, _ = render([reserved, "amount"], [("A", 2), ("B", 1)])
    table_only(result, "invalid_axis")
    assert response["tables"][0]["rows"][0][reserved] == "A"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_nonfinite_selected_values_cannot_reach_a_plot(value):
    result, _, _ = render(["label", "amount"], [("A", value), ("B", 1)])
    assert result["charts"] == []


@pytest.mark.parametrize("value", [9007199254740993, Decimal("-0.1234567890123456789")])
def test_exact_selected_values_use_table_fallback_without_rounded_coordinates(value):
    result, response, metadata = render(["label", "amount"], [("A", value), ("B", 1)])
    table_only(result, "precision_limit")
    assert metadata["exact_values"][0]["value"] == str(value)
    assert "approximate" not in response  # No alternate rounded result is invented.


def test_unused_exact_identifier_preserves_the_existing_whole_result_precision_policy():
    result, response, metadata = render(
        ["label", "amount", "record_id"],
        [("A", 2, 9007199254740993), ("B", 1, 7)],
    )
    table_only(result, "precision_limit")
    assert metadata["exact_values"][0]["column"] == "record_id"
    assert response["tables"][0]["rows"][0]["record_id"] == 9007199254740993


@pytest.mark.parametrize("count,reason", [(50, None), (51, "point_limit")])
def test_bar_boundary_refuses_excess_without_truncating_or_resumming(count, reason):
    rows = [(f"Category {index}", index - 25) for index in range(count)]
    result, response, _ = render(["label", "amount"], rows)
    assert len(response["tables"][0]["rows"]) == count
    if reason:
        table_only(result, reason)
    else:
        (chart,) = result["charts"]
        assert chart["row_indices"] == list(range(count))
        assert chart["input_rows"] == chart["output_points"] == count
        assert chart["reduction"] == "none" and chart["downsampled"] is False


@pytest.mark.parametrize("count,reason", [(500, None), (501, "point_limit")])
def test_time_boundary_keeps_exact_reference_order_or_falls_back(count, reason):
    rows = [
        (dt.date(2024, 1, 1) + dt.timedelta(days=i), i) for i in reversed(range(count))
    ]
    result, response, _ = render(["date", "amount"], rows)
    assert len(response["tables"][0]["rows"]) == count
    if reason:
        table_only(result, reason)
    else:
        (chart,) = result["charts"]
        assert chart["row_indices"] == list(reversed(range(count)))
        assert chart["output_points"] == count and chart["approximate"] is False


def test_equal_utc_instants_are_duplicates_despite_different_offset_spellings():
    first = dt.datetime(2026, 1, 1, 0, tzinfo=dt.timezone.utc)
    same = dt.datetime(2025, 12, 31, 19, tzinfo=dt.timezone(dt.timedelta(hours=-5)))
    result, _, _ = render(["instant", "amount"], [(first, 2), (same, 3)])
    table_only(result, "invalid_axis")


@pytest.mark.parametrize("mixed", [False, True])
def test_naive_time_is_not_silently_interpreted_in_the_browser_timezone(mixed):
    first = dt.datetime(2026, 1, 1)
    second = (
        dt.datetime(2026, 1, 2, tzinfo=dt.timezone.utc)
        if mixed
        else dt.datetime(2026, 1, 2)
    )
    result, _, _ = render(["instant", "amount"], [(first, 2), (second, 3)])
    table_only(result, "invalid_axis")


def test_compound_category_identity_never_collides_through_joined_label_text():
    result, _, _ = render(
        ["first", "second", "amount"], [("a b", "c", 2), ("a", "b c", 3)]
    )
    (chart,) = result["charts"]
    assert chart["x"]["keys"] == ["first", "second"]
    assert chart["row_indices"] == [0, 1] and chart["output_points"] == 2
    duplicate, _, _ = render(
        ["first", "second", "amount"], [("a", "b", 2), ("a", "b", 3)]
    )
    table_only(duplicate, "invalid_axis")


@pytest.mark.parametrize("day,reason", [(29, None), (30, "invalid_axis")])
def test_calendar_leap_reference_does_not_roll_invalid_dates_into_another_month(
    day, reason
):
    result, _, _ = render(
        ["year", "month", "day", "amount"], [(2024, 2, day, 2), (2024, 3, 1, 3)]
    )
    if reason:
        table_only(result, reason)
    else:
        (chart,) = result["charts"]
        assert chart["x"]["calendar_parts"] == ["year", "month", "day"]


def test_missing_negative_and_zero_values_are_not_replaced_or_silently_aggregated():
    result, response, metadata = render(
        ["label", "amount"], [("A", None), ("B", -4), ("C", 0)], truncated=True
    )
    (chart,) = result["charts"]
    assert chart["missing"] == "gap" and chart["row_indices"] == [0, 1, 2]
    assert [row["amount"] for row in response["tables"][0]["rows"]] == [None, -4, 0]
    assert metadata["truncated"] and metadata["aggregation"] == "unknown"
    assert chart["reduction"] == "none" and not chart["downsampled"]
    assert len(json.dumps(result).encode()) <= 65536
