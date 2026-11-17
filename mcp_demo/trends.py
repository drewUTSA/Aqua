"""Scope-bound historical fitting on original fixture data; no model training."""

import hashlib

from eval.banking.scope import scope_fingerprint
from eval.monthly_trend import fit_monthly_trend
from eval.monthly_trend_evaluation import evaluate_monthly_trend
from mcp_demo import data, reports
from mcp_demo.protocol import canonical, require, require_actor

SERIES_FIELDS = frozenset(
    {
        "metric_id",
        "definition",
        "unit",
        "aggregation",
        "complete",
        "truncated",
        "points",
        "dataset_revision",
        "as_of",
        "excluded_partial_periods",
        "source_origin",
        "synthetic",
        "complete_for_fixture_scope_only",
        "source_revision",
    }
)


def analyze_monthly_trend(actor, metric_id="gl_operating_surplus"):
    """Reuse the existing Decimal fit and chronological baseline evaluation."""
    require_actor(actor)
    # This fixed report grant is checked before accessing the ledger helper.
    reports.artifact_for(actor, "reconciliation_summary", 0)
    require(
        type(metric_id) is str and metric_id in reports.METRICS,
        "demo_metric_unknown",
    )
    series = reports.get_monthly_series(actor, metric_id)
    require(
        type(series) is dict
        and set(series) == SERIES_FIELDS
        and series["metric_id"] == metric_id
        and series["definition"] == reports.METRIC_DEFINITIONS[metric_id]
        and series["unit"] == "USD"
        and series["aggregation"] == "monthly_sum"
        and series["dataset_revision"] == data.SOURCE_REVISION
        and series["as_of"] == data.AS_OF
        and series["synthetic"] is True
        and series["complete_for_fixture_scope_only"] is True
        and series["excluded_partial_periods"] == [data.PERIOD],
        "demo_trend_source_invalid",
    )
    require(
        series["source_revision"]
        == hashlib.sha256(
            canonical({k: v for k, v in series.items() if k != "source_revision"})
        ).hexdigest(),
        "demo_trend_source_changed",
    )
    points = series["points"]
    require(
        type(points) is list
        and len(points) == 18
        and all(
            type(point) is dict
            and type(point.get("period")) is str
            and point["period"] < data.PERIOD + "-01"
            for point in points
        ),
        "demo_trend_history_invalid",
    )
    payload = {
        "version": 1,
        "source_sha256": series["source_revision"],
        "dataset_sha256": data.SOURCE_REVISION,
        "scope_sha256": scope_fingerprint(actor.scope),
        "unit": series["unit"],
        "aggregation": series["aggregation"],
        "complete": series["complete"],
        "truncated": series["truncated"],
        "points": points,
    }
    fit = fit_monthly_trend(payload)
    evaluation = evaluate_monthly_trend(payload)
    require(
        evaluation["status"] == "evaluated" and evaluation["evaluated_folds"] == 6,
        "demo_trend_evaluation_unavailable",
    )
    return {
        **data.provenance(),
        "metric_id": metric_id,
        "definition": series["definition"],
        "source_revision": series["source_revision"],
        "observations": points,
        "excluded_partial_periods": series["excluded_partial_periods"],
        "historical_fit": fit,
        "chronological_evaluation": evaluation,
        "qualification_established": False,
        "ollama_weights_updated": False,
        "interpretation": "fictional_history_not_a_forecast_or_bank_performance",
        "explanation": (
            "This describes 18 complete fictional ledger months. Six later "
            "observations were evaluated using only earlier observations, "
            "against a last-observation baseline. The partial November period "
            "is excluded. These checks do not establish future accuracy, "
            "causation or performance on a real bank."
        ),
    }
