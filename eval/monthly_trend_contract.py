"""Closed, offline monthly-series declarations; these are not authorization."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
import hashlib
import json
import re

MIN_POINTS, MAX_POINTS = 12, 120
UNITS = frozenset({"count", "CZK", "USD", "EUR", "GBP"})
FIELDS = frozenset(
    {
        "version",
        "source_sha256",
        "dataset_sha256",
        "scope_sha256",
        "unit",
        "aggregation",
        "complete",
        "truncated",
        "points",
    }
)
DECIMAL_TEXT = re.compile(r"-?(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,8})?\Z")


class TrendDenied(ValueError):
    """Fixed diagnostics never echo values, identifiers or private text."""


@dataclass(frozen=True)
class MonthlySeries:
    source: str
    dataset: str
    scope: str
    unit: str
    aggregation: str
    periods: tuple[str, ...]
    values: tuple[Decimal, ...]
    digest: str

    def binding(self):
        return {
            "source_sha256": self.source,
            "dataset_sha256": self.dataset,
            "scope_sha256": self.scope,
            "series_sha256": self.digest,
        }


def decimal_text(value):
    """Canonicalize bounded exact inputs without an ambient Decimal context."""
    if type(value) is str:
        if len(value) > 28 or DECIMAL_TEXT.fullmatch(value) is None:
            raise TrendDenied("trend_value_invalid")
        value = Decimal(value)
    elif type(value) is int:
        if not -(10**18) < value < 10**18:
            raise TrendDenied("trend_value_invalid")
        value = Decimal(value)
    elif type(value) is not Decimal:
        raise TrendDenied("trend_value_invalid")
    if not value.is_finite() or value.adjusted() > 17:
        raise TrendDenied("trend_value_invalid")
    parts = value.as_tuple()
    if parts.exponent < -8 or len(parts.digits) > 26:
        raise TrendDenied("trend_value_invalid")
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if value == 0 else text


def normalize(payload):
    if (
        type(payload) is not dict
        or len(payload) != len(FIELDS)
        or set(payload) != FIELDS
    ):
        raise TrendDenied("trend_contract_invalid")
    if type(payload["version"]) is not int or payload["version"] != 1:
        raise TrendDenied("trend_contract_invalid")
    for key in ("source_sha256", "dataset_sha256", "scope_sha256"):
        if (
            type(payload[key]) is not str
            or re.fullmatch(r"[0-9a-f]{64}", payload[key]) is None
        ):
            raise TrendDenied("trend_identity_invalid")
    if (
        type(payload["unit"]) is not str
        or len(payload["unit"]) > 5
        or payload["unit"] not in UNITS
    ):
        raise TrendDenied("trend_unit_unknown")
    expected = "monthly_count" if payload["unit"] == "count" else "monthly_sum"
    if type(payload["aggregation"]) is not str or payload["aggregation"] != expected:
        raise TrendDenied("trend_aggregation_invalid")
    if payload["complete"] is not True or payload["truncated"] is not False:
        raise TrendDenied("trend_incomplete")
    points = payload["points"]
    if type(points) is not list or not MIN_POINTS <= len(points) <= MAX_POINTS:
        raise TrendDenied("trend_point_budget")
    periods, values, normalized = [], [], []
    previous = None
    for point in points:
        if (
            type(point) is not dict
            or len(point) != 2
            or set(point) != {"period", "value"}
        ):
            raise TrendDenied("trend_point_invalid")
        period = point["period"]
        if (
            type(period) is not str
            or re.fullmatch(r"[0-9]{4}-[0-9]{2}-01", period) is None
        ):
            raise TrendDenied("trend_period_invalid")
        try:
            selected = date.fromisoformat(period)
        except ValueError:
            raise TrendDenied("trend_period_invalid") from None
        month = selected.year * 12 + selected.month
        if previous is not None and month != previous + 1:
            raise TrendDenied("trend_period_sequence")
        previous = month
        text = decimal_text(point["value"])
        value = Decimal(text)
        if payload["unit"] == "count" and (
            value < 0 or value != value.to_integral_value()
        ):
            raise TrendDenied("trend_count_invalid")
        periods.append(period)
        values.append(value)
        normalized.append({"period": period, "value": text})
    canonical = {**payload, "points": normalized}
    digest = hashlib.sha256(
        json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return MonthlySeries(
        payload["source_sha256"],
        payload["dataset_sha256"],
        payload["scope_sha256"],
        payload["unit"],
        payload["aggregation"],
        tuple(periods),
        tuple(values),
        digest,
    )
