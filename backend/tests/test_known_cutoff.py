"""An explicit known score excludes SQL NULL before ranking peers."""

import pytest
from sqlglot import exp
from nl2sql.answer_size import known_rank_measure
from nl2sql.execute import include_cutoff_peers
from nl2sql.validate import validate_sql


@pytest.mark.parametrize(
    "question,expected",
    [
        (
            "Which sensors had the highest known reading value? Include all ties.",
            "value",
        ),
        ("List the lowest three non-null calibration weights with ties.", "weight"),
        ("Which vans recorded the greatest nonnull fuel cost? Keep all ties.", "cost"),
        ("Which readings had the top 4 known totals?", "total"),
        ("What is the highest known rate among accounts?", "rate"),
        ("Which known accounts have the highest rates?", None),
        (
            "Which accounts had the highest known loan total, with unknown totals first?",
            None,
        ),
        (
            "Which accounts had the highest known loan total? Treat missing totals as zero.",
            None,
        ),
        (
            "Which accounts had the largest loan total, including accounts of unknown status?",
            None,
        ),
    ],
)
def test_requirement_belongs_to_the_ranked_value(question, expected):
    assert known_rank_measure(question) == expected


def wrap(raw, measure, n=2):
    q = validate_sql(raw, allowed_tables={"readings"})
    before = q.sql(dialect="postgres")
    edited = include_cutoff_peers(q, n, known_measure=measure)
    assert q.sql(dialect="postgres") == before
    return validate_sql(edited, allowed_tables={"readings"}) if edited else None


@pytest.mark.parametrize("null_order", ["NULLS FIRST", "NULLS LAST"])
@pytest.mark.parametrize("cutoff", ["LIMIT 2", "FETCH FIRST 2 ROWS WITH TIES"])
def test_known_sort_alias_filters_actual_score_before_a_qualified_limit(
    null_order, cutoff
):
    q = wrap(
        f"SELECT device_id, SUM(weight) AS total FROM readings WHERE device_id>0 GROUP BY device_id HAVING COUNT(*)>1 ORDER BY total DESC {null_order} {cutoff}",
        "total",
    )
    assert isinstance(q.args["having"].this, exp.And)
    pred = q.args["having"].find(exp.Is)
    assert isinstance(pred.this, exp.Sum) and pred.this.this.name == "weight"
    assert q.args["where"].find(exp.Is) is None
    assert q.args["limit"].args["limit_options"].args["with_ties"]


def test_known_hidden_scalar_appends_to_existing_row_filters():
    q = wrap(
        "SELECT device_id FROM readings WHERE device_id=1 OR device_id=3 ORDER BY reading_value NULLS FIRST LIMIT 2",
        "value",
    )
    assert isinstance(q.args["where"].this, exp.And)
    assert (
        q.args["where"].find(exp.Or)
        and q.args["where"].find(exp.Is).this.name == "reading_value"
    )


@pytest.mark.parametrize(
    "raw,metric",
    [
        (
            "SELECT device_id,status AS weight FROM readings ORDER BY weight FETCH FIRST 2 ROWS WITH TIES",
            "weight",
        ),
        (
            "SELECT device_id,COUNT(*) AS total FROM readings GROUP BY device_id ORDER BY total FETCH FIRST 2 ROWS WITH TIES",
            "total",
        ),
        (
            "SELECT device_id,COALESCE(weight,0) AS weight FROM readings ORDER BY weight FETCH FIRST 2 ROWS WITH TIES",
            "weight",
        ),
        (
            "SELECT device_id,weight FROM readings ORDER BY weight,device_id LIMIT 2",
            "weight",
        ),
        (
            "SELECT device_id,weight FROM readings ORDER BY weight OFFSET 2 LIMIT 2",
            "weight",
        ),
    ],
)
def test_no_unproved_metric_or_changed_ranking_basis(raw, metric):
    assert wrap(raw, metric) is None
