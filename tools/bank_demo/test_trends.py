"""Independent arithmetic and authority checks for the demo trend adapter."""

from copy import deepcopy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from eval.banking.data import BankingDenied  # noqa: E402
from eval.monthly_trend_contract import TrendDenied  # noqa: E402
from mcp_demo import data, reports  # noqa: E402
from mcp_demo.protocol import DemoDenied, actor_for, canonical  # noqa: E402
from mcp_demo.trends import analyze_monthly_trend  # noqa: E402


def rebind(series):
    series["source_revision"] = hashlib.sha256(
        canonical({k: v for k, v in series.items() if k != "source_revision"})
    ).hexdigest()
    return series


class TrendTests(unittest.TestCase):
    def test_real_fixture_excludes_partial_month_and_keeps_learning_claims_false(self):
        result = analyze_monthly_trend(actor_for("analyst"))
        fit, evaluation = result["historical_fit"], result["chronological_evaluation"]
        self.assertEqual(
            (fit["observed_start"], fit["observed_end"]), ("2025-05-01", "2026-10-01")
        )
        self.assertEqual(
            (fit["observed_points"], evaluation["evaluated_folds"]), (18, 6)
        )
        self.assertEqual(result["excluded_partial_periods"], ["2026-11"])
        self.assertTrue(result["synthetic"])
        self.assertFalse(result["qualification_established"])
        self.assertFalse(fit["qualification_established"])
        self.assertFalse(evaluation["qualification_established"])
        self.assertFalse(result["ollama_weights_updated"])
        self.assertEqual(fit["binding"], evaluation["binding"])
        self.assertEqual(fit["binding"]["dataset_sha256"], data.SOURCE_REVISION)

    def test_hand_derived_linear_history_has_zero_fit_and_holdout_error(self):
        actor = actor_for("analyst")
        series = deepcopy(reports.get_monthly_series(actor, "gl_operating_surplus"))
        # y=100+10x: slope10, intercept100; six last-value errors are all10.
        for index, point in enumerate(series["points"]):
            point["value"] = str(100 + 10 * index)
        with patch("mcp_demo.reports.get_monthly_series", return_value=rebind(series)):
            result = analyze_monthly_trend(actor)
        fit, evaluation = result["historical_fit"], result["chronological_evaluation"]
        self.assertEqual(
            (
                fit["slope_per_month"],
                fit["intercept"],
                fit["in_sample_mae"],
                fit["in_sample_r_squared"],
            ),
            ("10", "100", "0", "1"),
        )
        self.assertEqual(evaluation["trend"], {"mae": "0", "rmse": "0"})
        self.assertEqual(evaluation["last_observation"], {"mae": "10", "rmse": "10"})
        self.assertEqual(evaluation["mae_comparison"], "lower_error")

    def test_scopes_deny_before_reading_source(self):
        for persona in ("none", "teller"):
            with patch("mcp_demo.reports.get_monthly_series") as loader:
                with self.assertRaises((DemoDenied, BankingDenied)):
                    analyze_monthly_trend(actor_for(persona))
                loader.assert_not_called()
        analyst = analyze_monthly_trend(actor_for("analyst"))
        manager = analyze_monthly_trend(actor_for("manager"))
        self.assertNotEqual(
            analyst["historical_fit"]["binding"]["scope_sha256"],
            manager["historical_fit"]["binding"]["scope_sha256"],
        )

    def test_changed_data_revision_or_source_hash_is_denied(self):
        actor = actor_for("analyst")
        original = reports.get_monthly_series(actor, "gl_operating_surplus")
        for field, value in (
            ("dataset_revision", "f" * 64),
            ("source_revision", "0" * 64),
            ("as_of", "2027-01-01"),
            ("metric_id", "gl_operating_income"),
        ):
            with (
                self.subTest(field=field),
                patch(
                    "mcp_demo.reports.get_monthly_series",
                    return_value={**original, field: value},
                ),
            ):
                with self.assertRaises(DemoDenied):
                    analyze_monthly_trend(actor)

    def test_missing_month_duplicate_partial_and_incomplete_data_are_denied(self):
        actor = actor_for("analyst")
        original = reports.get_monthly_series(actor, "gl_operating_surplus")
        variants = []
        missing = deepcopy(original)
        missing["points"].pop(5)
        variants.append(missing)
        duplicate = deepcopy(original)
        duplicate["points"][5]["period"] = duplicate["points"][4]["period"]
        variants.append(duplicate)
        partial = deepcopy(original)
        partial["points"][-1]["period"] = "2026-11-01"
        variants.append(partial)
        variants.extend(
            [
                {**deepcopy(original), "complete": False},
                {**deepcopy(original), "truncated": True},
            ]
        )
        for index, series in enumerate(variants):
            with (
                self.subTest(index=index),
                patch(
                    "mcp_demo.reports.get_monthly_series", return_value=rebind(series)
                ),
            ):
                with self.assertRaises((DemoDenied, TrendDenied)):
                    analyze_monthly_trend(actor)

    def test_only_closed_server_metrics_accept_no_caller_data(self):
        for metric in reports.METRICS:
            self.assertEqual(
                analyze_monthly_trend(actor_for("analyst"), metric)["metric_id"], metric
            )
        for metric in ("payments", "revenue; DROP TABLE", None, {"points": []}):
            with self.assertRaises(DemoDenied):
                analyze_monthly_trend(actor_for("analyst"), metric)


if __name__ == "__main__":
    unittest.main()
