"""Chronological expanding-window checks against a last-observation baseline."""

from decimal import Decimal, localcontext

from eval.monthly_trend import ARITHMETIC, METHOD, _fit, number
from eval.monthly_trend_contract import MIN_POINTS, normalize

MIN_EVALUATION_FOLDS = 6


def evaluate_monthly_trend(payload):
    series = normalize(payload)
    trend_errors, last_errors = [], []
    # Every eligible observation is held out once. Its value is not available
    # to the fit or last-value baseline used to evaluate that observation.
    with localcontext(ARITHMETIC):
        for held_out in range(MIN_POINTS, len(series.values)):
            history = series.values[:held_out]
            fitted = _fit(history)
            actual = series.values[held_out]
            trend_errors.append(actual - fitted.at(held_out))
            last_errors.append(actual - history[-1])
        folds = len(trend_errors)

        def metrics(errors):
            if not errors:
                return {"mae": None, "rmse": None}
            count = Decimal(len(errors))
            return {
                "mae": number(sum(map(abs, errors), Decimal(0)) / count),
                "rmse": number(
                    (sum((error**2 for error in errors), Decimal(0)) / count).sqrt()
                ),
            }

        enough = folds >= MIN_EVALUATION_FOLDS
        comparison = "insufficient_history"
        if enough:
            trend_total = sum(map(abs, trend_errors), Decimal(0))
            last_total = sum(map(abs, last_errors), Decimal(0))
            comparison = (
                "lower_error"
                if trend_total < last_total
                else "higher_error" if trend_total > last_total else "equal_error"
            )
        return {
            "version": 1,
            "kind": "historical_rolling_origin_evaluation",
            "method": METHOD,
            "baseline": "last_observation_v1",
            "approximate": True,
            "binding": series.binding(),
            "unit": series.unit,
            "training_minimum_points": MIN_POINTS,
            "eligible_folds": folds,
            "evaluated_folds": folds,
            "minimum_evaluation_folds": MIN_EVALUATION_FOLDS,
            "status": "evaluated" if enough else "insufficient_history",
            "first_evaluation_period": series.periods[MIN_POINTS] if folds else None,
            "last_evaluation_period": series.periods[-1] if folds else None,
            "trend": metrics(trend_errors),
            "last_observation": metrics(last_errors),
            "mae_comparison": comparison,
            "qualification_established": False,
            "interpretation": "observed_holdouts_only_not_future_performance",
        }
