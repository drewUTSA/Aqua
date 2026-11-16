"""Fit a bounded historical trend; no database, model calls or future forecasts."""

from dataclasses import dataclass
from decimal import Context, Decimal, ROUND_HALF_EVEN, localcontext

from eval.monthly_trend_contract import normalize

ARITHMETIC = Context(prec=48, rounding=ROUND_HALF_EVEN, Emin=-999, Emax=999)
METHOD = "ols_monthly_v1"


@dataclass(frozen=True)
class Fit:
    intercept: Decimal
    slope: Decimal
    mae: Decimal
    rmse: Decimal
    r_squared: Decimal | None

    def at(self, month_index):
        # Used only for observed-period fit/evaluation, not public forecasting.
        with localcontext(ARITHMETIC):
            return self.intercept + self.slope * Decimal(month_index)


def number(value):
    """Finite approximate metrics are decimal strings, never lossy JSON floats."""
    if value is None:
        return None
    with localcontext(ARITHMETIC):
        text = format(value.quantize(Decimal("0.000000000000000001")), "f")
    text = text.rstrip("0").rstrip(".")
    return "0" if Decimal(text) == 0 else text


def _fit(values):
    """Centered OLS on consecutive integer month indices, using fixed precision."""
    with localcontext(ARITHMETIC):
        count = Decimal(len(values))
        mean_x = (count - 1) / 2
        mean_y = sum(values, Decimal(0)) / count
        covariance = sum(
            (
                (Decimal(i) - mean_x) * (value - mean_y)
                for i, value in enumerate(values)
            ),
            Decimal(0),
        )
        variance = sum(
            ((Decimal(i) - mean_x) ** 2 for i in range(len(values))), Decimal(0)
        )
        slope = covariance / variance
        intercept = mean_y - slope * mean_x
        residuals = [
            value - (intercept + slope * Decimal(i)) for i, value in enumerate(values)
        ]
        sse = sum((error**2 for error in residuals), Decimal(0))
        sst = sum(((value - mean_y) ** 2 for value in values), Decimal(0))
        r_squared = (
            None if sst == 0 else max(Decimal(0), min(Decimal(1), 1 - sse / sst))
        )
        return Fit(
            intercept,
            slope,
            sum(map(abs, residuals), Decimal(0)) / count,
            (sse / count).sqrt(),
            r_squared,
        )


def fit_monthly_trend(payload):
    series = normalize(payload)
    fit = _fit(series.values)
    return {
        "version": 1,
        "kind": "historical_monthly_trend",
        "method": METHOD,
        "approximate": True,
        "qualification_established": False,
        "ollama_weights_updated": False,
        "binding": series.binding(),
        "unit": series.unit,
        "aggregation": series.aggregation,
        "observed_start": series.periods[0],
        "observed_end": series.periods[-1],
        "observed_points": len(series.values),
        "month_index_origin": series.periods[0],
        "intercept": number(fit.intercept),
        "slope_per_month": number(fit.slope),
        "fitted_direction": (
            "rising" if fit.slope > 0 else "falling" if fit.slope < 0 else "flat"
        ),
        "in_sample_mae": number(fit.mae),
        "in_sample_rmse": number(fit.rmse),
        "in_sample_r_squared": number(fit.r_squared),
        "interpretation": "historical_fit_not_forecast_or_causation",
    }
