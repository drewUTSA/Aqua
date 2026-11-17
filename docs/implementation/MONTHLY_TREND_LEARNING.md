# Offline monthly trend learning

> **Latest session: stopped November 17 UTC.** Read the [complete next-chat handoff](PERSONAL_COMPUTER_RESUME_20261117.md).
> Production remains on schema 8; the current operator is unfinished. Earlier sections retain their historical scope.

This first numerical-learning slice fits a historical straight-line baseline
to an explicitly supplied monthly aggregate. It does not change Ollama's
weights, infer causes, produce future forecasts, read a database, invoke a
provider, create an application route or persist a shared model. No feature is
enabled. Exact financial tables, chart descriptors and precision metadata are
unchanged. The output is a separate **approximate historical insight**.

`eval.monthly_trend.fit_monthly_trend(payload)` learns OLS intercept/slope from
the supplied observations and reports in-sample MAE, RMSE and R-squared. Constant
series have undefined R-squared, reported as null. The direction describes the
sign of the fitted slope; it is not a significance or confidence statement.

The closed version-1 payload contains only `version`, `source_sha256`,
`dataset_sha256`, `scope_sha256`, `unit`, `aggregation`, `complete`, `truncated`
and `points`. All three identities are lowercase SHA256 strings. Units are
explicitly `count`, `CZK`, `USD`, `EUR` or `GBP`; counts require
`aggregation: monthly_count`, other units `monthly_sum`. `complete` must be
true and `truncated` false. Each of 12–120 points has exactly `period` and
`value`, in strictly consecutive YYYY-MM-01 order. Gaps, duplicate months,
partial months, timestamps and reordered data are refused rather than repaired.

Values are bounded finite Decimals, integers or ordinary decimal strings;
floats, booleans, scientific-notation strings and nonfinite values are rejected.
Inputs have at most 18 integer digits and eight fractional places. Counts must
be nonnegative integers. Arithmetic uses a fixed 48-digit Decimal context;
reported approximate coefficients/metrics are strings rounded to 18 fractional
places, with trailing zeros omitted. This preserves input precision without
pretending fitted values are exact accounting totals. Nothing is silently
zero-filled, interpolated, grouped, currency-converted or charted.

**Identity, completeness, aggregation and unit fields are declarations, not
authorization proof.** The offline tool cannot verify source freshness or that
a caller selected a complete period. A future integration must derive those
facts from trusted reviewed query/aggregation metadata, preserve current
owner/dataset/grant/deadline checks and reject ambiguous/truncated results. The
current result metadata's unknown aggregation/freshness does not satisfy this
contract automatically. Do not wrap arbitrary returned date/number columns and
claim a complete training series.

## Historical evaluation

`eval.monthly_trend_evaluation.evaluate_monthly_trend(payload)` uses every
eligible chronological fold. After the first 12 observations, it fits only
earlier months and evaluates the next already-observed month. The last-value
baseline uses the identical folds and only that same earlier history. It
reports aggregate MAE/RMSE for both methods, eligible/evaluated fold counts and
the evaluation period range; no future extrapolated point is returned.

With fewer than six eligible folds it explicitly reports insufficient history.
Any available folds still count and their metrics remain visible. With no
eligible folds metrics are null. Six folds are only a conservative reporting
floor, not evidence of statistical significance. Higher model error, ties and
lower error are distinguished. No case is dropped because the fit performs
poorly, and `qualification_established` remains false in every output.

Model selection, anomaly thresholds, seasonal methods, confidence intervals,
out-of-sample deployment quality and model-triggered actions remain outside this
slice. Seasonal data can perform worse than the last-value baseline, which the
synthetic tests demonstrate. Qualification on a suitable reviewed, authorized
dataset is required before considering integration; the absent live analytical
endpoint does not block these independent synthetic checks.

## Synthetic verification

Run the focused suite in the existing approved test environment:

```text
python -m pytest -q backend/tests/test_monthly_trend.py
```

Tests cover rising/falling/flat lines, noisy and seasonal series, coefficients
beyond JavaScript's exact-integer range, ambient Decimal-context independence,
every chronological fold, future-spike leakage, insufficient history, errors
versus the naive baseline, gaps/duplicates/order/date semantics, units/counts,
scope/complete/truncated declarations, numeric/resource bounds, deterministic
bindings and fixed non-reflecting diagnostics. All observations are generated
synthetically. No company corpus, actual account data, new package, model call,
training checkpoint or production query is used.
