"""Synthetic numerical learning: no providers, database, app routes or real data."""

import copy
from decimal import Decimal, ROUND_UP, localcontext
import json

import pytest

from eval.monthly_trend import fit_monthly_trend
from eval.monthly_trend_contract import TrendDenied, normalize
import eval.monthly_trend_evaluation as evaluation


def series(values, **changes):
    payload = {
        "version": 1,
        "source_sha256": "a" * 64,
        "dataset_sha256": "b" * 64,
        "scope_sha256": "c" * 64,
        "unit": "CZK",
        "aggregation": "monthly_sum",
        "complete": True,
        "truncated": False,
        "points": [
            {"period": f"{1993 + i // 12:04d}-{1 + i % 12:02d}-01", "value": value}
            for i, value in enumerate(values)
        ],
    }
    payload.update(changes)
    return payload


@pytest.mark.parametrize(
    ("slope", "direction"), [(3, "rising"), (-4, "falling"), (0, "flat")]
)
def test_known_historical_lines_learn_coefficients_without_claiming_future(
    slope, direction
):
    payload = series([1000 + slope * i for i in range(24)])
    original = copy.deepcopy(payload)
    result = fit_monthly_trend(payload)
    assert result["intercept"] == "1000"
    assert result["slope_per_month"] == str(slope)
    assert result["fitted_direction"] == direction
    assert result["in_sample_mae"] == result["in_sample_rmse"] == "0"
    assert result["in_sample_r_squared"] == (None if slope == 0 else "1")
    assert result["approximate"] is True
    assert result["qualification_established"] is False
    assert result["ollama_weights_updated"] is False
    assert result["interpretation"] == "historical_fit_not_forecast_or_causation"
    assert (
        not {"forecast", "confidence", "rows", "charts", "predicted_periods"}
        & result.keys()
    )
    assert payload == original


def test_large_money_inputs_and_small_slope_keep_decimal_precision():
    base = Decimal("9007199254740993.12")
    result = fit_monthly_trend(series([base + Decimal("0.01") * i for i in range(24)]))
    assert result["intercept"] == "9007199254740993.12"
    assert result["slope_per_month"] == "0.01"
    assert result["in_sample_rmse"] == "0"
    assert type(result["intercept"]) is str


def test_ambient_decimal_context_cannot_change_a_fit_or_evaluation():
    payload = series([f"{1000 + (i * 17) % 13}.12345678" for i in range(30)])
    expected = fit_monthly_trend(payload), evaluation.evaluate_monthly_trend(payload)
    with localcontext() as context:
        context.prec = 2
        context.rounding = ROUND_UP
        assert (
            fit_monthly_trend(payload),
            evaluation.evaluate_monthly_trend(payload),
        ) == expected


def test_noisy_fit_reports_nonzero_error_and_no_quality_claim():
    payload = series([1000 + (i * 17) % 13 - 6 for i in range(36)])
    result = fit_monthly_trend(payload)
    assert Decimal(result["in_sample_rmse"]) > 0
    assert Decimal(result["in_sample_r_squared"]) < Decimal("0.1")
    assert result["qualification_established"] is False


@pytest.mark.parametrize("count", [12, 13, 17, 18, 120])
def test_every_eligible_chronological_fold_is_retained_in_both_models(count):
    result = evaluation.evaluate_monthly_trend(
        series([100 + i * 2 for i in range(count)])
    )
    assert result["eligible_folds"] == result["evaluated_folds"] == count - 12
    assert result["status"] == ("evaluated" if count >= 18 else "insufficient_history")
    assert result["mae_comparison"] == (
        "lower_error" if count >= 18 else "insufficient_history"
    )
    assert result["qualification_established"] is False
    if count == 12:
        assert (
            result["trend"] == result["last_observation"] == {"mae": None, "rmse": None}
        )
        assert (
            result["first_evaluation_period"]
            is result["last_evaluation_period"]
            is None
        )
    else:
        assert result["trend"]["mae"] == "0"
        assert result["last_observation"]["mae"] == "2"


def test_constant_baseline_tie_is_not_called_an_improvement():
    result = evaluation.evaluate_monthly_trend(series([100] * 24))
    assert result["mae_comparison"] == "equal_error"
    assert result["trend"] == result["last_observation"] == {"mae": "0", "rmse": "0"}


def test_seasonal_series_exposes_linear_model_worse_than_last_value():
    cycle = [0, 50, 87, 100, 87, 50, 0, -50, -87, -100, -87, -50]
    result = evaluation.evaluate_monthly_trend(
        series([1000 + cycle[i % 12] for i in range(36)])
    )
    assert result["mae_comparison"] == "higher_error"
    assert Decimal(result["trend"]["mae"]) > Decimal(result["last_observation"]["mae"])
    assert result["evaluated_folds"] == 24
    assert result["qualification_established"] is False


def test_each_fit_sees_only_earlier_observations_even_after_future_spike(monkeypatch):
    payload = series([100 + i for i in range(24)])
    payload["points"][20]["value"] = 900000
    values = normalize(payload).values
    original_fit = evaluation._fit
    seen = []

    def observed(history):
        seen.append(tuple(history))
        return original_fit(history)

    monkeypatch.setattr(evaluation, "_fit", observed)
    evaluation.evaluate_monthly_trend(payload)
    assert [len(history) for history in seen] == list(range(12, 24))
    assert all(
        history == values[:held_out] for held_out, history in enumerate(seen, 12)
    )
    assert Decimal(900000) not in seen[8]  # The spike is the ninth held-out point.
    assert Decimal(900000) in seen[9]


@pytest.mark.parametrize(
    "value",
    [
        True,
        1.2,
        float("nan"),
        None,
        "NaN",
        "Infinity",
        "1e3",
        "1.000000001",
        "0" * 1000,
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("1E999999"),
        Decimal("1E-9"),
        10**18,
    ],
)
def test_invalid_or_unbounded_values_fail_with_fixed_diagnostics(value):
    payload = series([1] * 12)
    payload["points"][0]["value"] = value
    with pytest.raises(TrendDenied, match="^trend_value_invalid$"):
        fit_monthly_trend(payload)


@pytest.mark.parametrize(
    "change",
    [
        "gap",
        "duplicate",
        "reverse",
        "not_month_start",
        "timestamp",
        "invalid_date",
        "string_period",
        "extra_point_field",
    ],
)
def test_missing_duplicate_unsorted_or_ambiguous_periods_are_not_repaired(change):
    payload = series([1] * 12)
    if change == "gap":
        payload["points"][1]["period"] = "1993-03-01"
    elif change == "duplicate":
        payload["points"][1]["period"] = "1993-01-01"
    elif change == "reverse":
        payload["points"].reverse()
    elif change == "extra_point_field":
        payload["points"][0]["prompt"] = "PRIVATE_SENTINEL"
    else:
        payload["points"][0]["period"] = {
            "not_month_start": "1993-01-02",
            "timestamp": "1993-01-01T00:00:00Z",
            "invalid_date": "0000-01-01",
            "string_period": "January 1993",
        }[change]
    with pytest.raises(TrendDenied) as denied:
        fit_monthly_trend(payload)
    assert str(denied.value).startswith("trend_")
    assert "PRIVATE_SENTINEL" not in str(denied.value)


@pytest.mark.parametrize(
    "change",
    [
        {"complete": False},
        {"complete": 1},
        {"truncated": True},
        {"truncated": 0},
        {"unit": "unknown"},
        {"unit": "SECRET_SENTINEL"},
        {"aggregation": "unknown"},
        {"source_sha256": "SECRET_SENTINEL"},
        {"dataset_sha256": None},
        {"scope_sha256": "D" * 64},
        {"version": True},
        {"prompt": "SECRET_SENTINEL"},
    ],
)
def test_scope_units_and_completeness_must_be_explicit_but_are_not_authority(change):
    with pytest.raises(TrendDenied) as denied:
        fit_monthly_trend(series([1] * 12, **change))
    assert "SECRET_SENTINEL" not in str(denied.value)


@pytest.mark.parametrize("count", [0, 11, 121])
def test_series_resource_bounds_are_closed(count):
    with pytest.raises(TrendDenied, match="^trend_point_budget$"):
        fit_monthly_trend(series([1] * count))


def test_count_unit_has_integral_nonnegative_observations():
    payload = series(list(range(12)), unit="count", aggregation="monthly_count")
    assert fit_monthly_trend(payload)["unit"] == "count"
    for value in (-1, "1.5"):
        payload["points"][0]["value"] = value
        with pytest.raises(TrendDenied, match="^trend_count_invalid$"):
            fit_monthly_trend(payload)


def test_binding_is_deterministic_scoped_and_does_not_echo_series():
    payload = series(["1.000"] * 24)
    equivalent = series([Decimal("1")] * 24)
    result = fit_monthly_trend(payload)
    assert result["binding"] == fit_monthly_trend(equivalent)["binding"]
    changed = copy.deepcopy(payload)
    changed["scope_sha256"] = "d" * 64
    assert (
        result["binding"]["series_sha256"]
        != fit_monthly_trend(changed)["binding"]["series_sha256"]
    )
    assert "points" not in result and len(json.dumps(result)) < 4096
