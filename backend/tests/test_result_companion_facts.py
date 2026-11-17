"""Independent arithmetic/precision/shape assertions, entirely provider-free."""

from copy import deepcopy
import json

import pytest

from result_companion.facts import build
from result_companion_fixtures import response


def brief(value=None, column=0, check=lambda: None):
    return build(
        response() if value is None else value,
        "Original synthetic question",
        column,
        check,
    )


def test_useful_profile_is_not_the_existing_leading_row_summary_or_currency_guess():
    result = brief(response(truncated=True))
    assert result["counts"] == {
        "returned_rows": 5,
        "missing_values": 1,
        "non_missing_values": 4,
    }
    assert result["numeric"] == {
        "minimum": {"value": "-3.5", "ties": 1, "witness_rows": [1]},
        "maximum": {"value": "7", "ties": 2, "witness_rows": [0, 3]},
    }
    assert result["scope"] == {
        "basis": "returned_rows_only",
        "truncated": True,
        "max_rows": 1000,
        "filters": "unknown",
        "aggregation": "unknown",
        "precision": "sidecar_preferred",
    }
    assert result["field"]["unit"] is None and result["source"]["freshness_at"] is None
    assert [item["id"] for item in result["checks"]] == [
        "returned_subset",
        "missing_values",
        "units_unknown",
        "freshness_unknown",
        "scope_unknown",
    ]
    assert result["followup_intents"] == [
        "verify_scope",
        "missing_values",
        "compare_field",
    ]
    raw = json.dumps(result)
    assert (
        "PRIVATE_SQL_CANARY" not in raw
        and "PRIVATE_SUMMARY_CANARY" not in raw
        and '"USD"' not in raw
    )
    assert result["execution_enabled"] is False


def test_adjacent_unsafe_integers_and_subcent_decimals_do_not_collapse_into_ties():
    integers = [9007199254740993, 9007199254740994, 9007199254740993]
    exact = [
        {"row": i, "column": "value", "value": str(value), "kind": "integer"}
        for i, value in enumerate(integers)
    ]
    numeric = brief(response(integers, exact=exact))["numeric"]
    assert numeric["minimum"] == {
        "value": "9007199254740993",
        "ties": 2,
        "witness_rows": [0, 2],
    }
    assert numeric["maximum"] == {
        "value": "9007199254740994",
        "ties": 1,
        "witness_rows": [1],
    }
    decimals = [
        {"row": i, "column": "value", "value": value, "kind": "decimal"}
        for i, value in enumerate(["1.0000000000000000002", "1.0000000000000000001"])
    ]
    numeric = brief(response([1.0, 1.0], exact=decimals))["numeric"]
    assert numeric["minimum"]["value"] == "1.0000000000000000001" and numeric[
        "minimum"
    ]["witness_rows"] == [1]
    assert (
        numeric["maximum"]["value"] == "1.0000000000000000002"
        and numeric["maximum"]["ties"] == 1
    )


def test_tie_witnesses_are_bounded_without_hiding_the_full_returned_tie_count():
    result = brief(response([2] * 5))["numeric"]
    assert (
        result["minimum"]
        == result["maximum"]
        == {"value": "2", "ties": 5, "witness_rows": [0, 1, 2]}
    )


@pytest.mark.parametrize(
    "values,kind,missing",
    [
        ([], "empty", 0),
        ([None, None], "empty", 2),
        (["12", "NULL", ""], "text", 0),
        ([True, False], "boolean", 0),
        ([12, "12", True, None], "mixed", 1),
    ],
)
def test_empty_null_and_non_numeric_fields_are_not_financial_comparisons(
    values, kind, missing
):
    result = brief(response(values))
    assert (
        result["status"] == "ready"
        and result["field"]["kind"] == kind
        and result["numeric"] is None
    )
    assert result["counts"]["missing_values"] == missing
    assert "compare_field" not in result["followup_intents"]


def test_legacy_is_honestly_limited_even_for_a_large_saved_numeric_value():
    result = brief(response([10**300, None], metadata=False))
    assert result["status"] == "limited" and result["numeric"] is None
    assert result["source"] == {"id": None, "generated_at": None, "freshness_at": None}
    assert result["scope"]["max_rows"] is None and result["scope"]["truncated"] is None
    assert result["checks"][-1]["id"] == "precision_unverified"
    assert result["followup_intents"] == ["verify_scope", "missing_values"]


@pytest.mark.parametrize(
    "attack",
    [
        "extra_metadata",
        "null_metadata",
        "wrong_units",
        "freshness_claim",
        "naive_timestamp",
        "bool_version",
        "wrong_limit",
        "duplicate_pointer",
        "wrong_integer",
        "text_pointer",
        "pointer_range",
        "bool_pointer",
        "bad_number",
        "number_overflow",
        "missing_sidecar",
        "duplicate_column",
        "missing_cell",
        "too_many_rows",
        "nonfinite",
    ],
)
def test_malformed_descriptor_or_shape_fails_instead_of_downgrading_or_guessing(attack):
    value = response(
        [9007199254740993],
        exact=[
            {
                "row": 0,
                "column": "value",
                "value": "9007199254740993",
                "kind": "integer",
            }
        ],
    )
    meta = value["result_metadata"]
    if attack == "extra_metadata":
        meta["trusted"] = True
    elif attack == "null_metadata":
        value["result_metadata"] = None
    elif attack == "wrong_units":
        meta["column_units"]["value"] = "USD"
    elif attack == "freshness_claim":
        meta["source"]["freshness_at"] = meta["generated_at"]
    elif attack == "naive_timestamp":
        meta["generated_at"] = "2026-11-17"
    elif attack == "bool_version":
        meta["version"] = True
    elif attack == "wrong_limit":
        meta["max_rows"] = True
    elif attack == "duplicate_pointer":
        meta["exact_values"] *= 2
    elif attack == "wrong_integer":
        meta["exact_values"][0]["value"] = "9007199254740992"
    elif attack == "text_pointer":
        value["tables"][0]["rows"][0]["value"] = "9007199254740993"
    elif attack == "pointer_range":
        meta["exact_values"][0]["row"] = 1
    elif attack == "bool_pointer":
        meta["exact_values"][0]["row"] = True
    elif attack == "bad_number":
        meta["exact_values"][0]["value"] = "1e3"
    elif attack == "number_overflow":
        meta["exact_values"][0]["value"] = "1" * 257
    elif attack == "missing_sidecar":
        meta["exact_values"] = []
    elif attack == "duplicate_column":
        value["tables"][0]["columns"] *= 2
    elif attack == "missing_cell":
        value["tables"][0]["rows"][0] = {}
    elif attack == "too_many_rows":
        value["tables"][0]["rows"] *= 1001
    else:
        value["tables"][0]["rows"][0]["value"] = float("nan")
    with pytest.raises(ValueError):
        brief(value)


def test_selected_column_and_every_witness_are_bound_to_the_actual_saved_table():
    value = response([3, 9])
    table = value["tables"][0]
    table["columns"].append({"key": "other", "label": "Other", "type": "number"})
    for row, other in zip(table["rows"], [15, -2], strict=True):
        row["other"] = other
    value["result_metadata"]["column_units"]["other"] = None
    result = brief(value, 1)
    assert result["field"]["index"] == 1 and result["field"]["key"] == "other"
    assert result["numeric"]["minimum"] == {
        "value": "-2",
        "ties": 1,
        "witness_rows": [1],
    }
    original = deepcopy(value)
    brief(value)
    assert value == original


def test_integral_decimal_sidecar_binds_to_an_unrounded_large_json_integer():
    value = response(
        [9007199254740993],
        exact=[
            {
                "row": 0,
                "column": "value",
                "value": "9007199254740993.0",
                "kind": "decimal",
            }
        ],
    )
    assert brief(value)["numeric"]["maximum"]["value"] == "9007199254740993.0"
    value["result_metadata"]["exact_values"][0]["value"] = "9007199254740993.1"
    with pytest.raises(ValueError):
        brief(value)


def test_unsafe_integral_float_needs_a_valid_exact_sidecar_before_comparison():
    raw = float(9007199254740993)
    with pytest.raises(ValueError):
        brief(response([raw]))
    for kind, shown in (
        ("integer", "9007199254740993"),
        ("decimal", "9007199254740993.0"),
    ):
        result = brief(
            response(
                [raw],
                exact=[{"row": 0, "column": "value", "value": shown, "kind": kind}],
            )
        )
        assert result["numeric"]["minimum"]["value"] == shown
        assert result["numeric"]["maximum"]["value"] == shown


def test_cooperative_budget_is_checked_during_row_projection():
    ticks = []

    def check():
        ticks.append(1)
        if len(ticks) == 7:
            raise TimeoutError("fixture_deadline")

    with pytest.raises(TimeoutError):
        brief(response(range(1000)), check=check)
    assert len(ticks) == 7
