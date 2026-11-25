"""Execution stays internal; authorized employees receive useful answer data."""

import copy
import json

import pytest

from privacy.result_fragment import validated_bytes
from workspace.ranking_fields import ranking_fields
from workspace.result_view import employee_result
from workspace_fixtures import GOOD

SQL = "SELECT counter_id, COUNT(*) AS visits FROM public.turnstiles GROUP BY counter_id ORDER BY visits DESC LIMIT 2"
QUESTION = "Which are the top two counters by visit count?"
HINT = {
    "source": "turnstiles",
    "group": "counter_id",
    "measure": "count",
    "field": "",
    "direction": "top",
    "number": "2",
    "ties": "",
}


def test_projection_preserves_internal_execution_and_returns_only_review_fields():
    original = {
        **GOOD,
        "sql": SQL,
        "tables": [{"title": QUESTION, "rows": [{"visits": 7}]}],
        "internal_query": SQL,
        "user_id": "private-owner",
    }
    before = copy.deepcopy(original)
    public = employee_result(original)
    assert original == before and original["sql"] == SQL
    assert public["tables"] == original["tables"] and public["sql"] == ""
    assert public["rank_fields"] == HINT
    assert SQL not in json.dumps(public) and "private-owner" not in json.dumps(public)
    error = employee_result(
        {
            **original,
            "status": "error",
            "error": {
                "code": "rejected",
                "message": "Refused",
                "retryable": False,
                "sql": SQL,
            },
        }
    )
    assert "rank_fields" not in error and SQL not in json.dumps(error)
    assert employee_result(None) is None


@pytest.mark.parametrize("order", ["visits", "COUNT(*)", "2"])
def test_saved_simple_grouped_count_retains_review_without_sql(order):
    assert ranking_fields(SQL.replace("BY visits", "BY " + order), QUESTION) == HINT
    assert ranking_fields(SQL.upper(), QUESTION) == HINT


def test_aliased_total_and_fetch_keep_physical_fields_without_selecting_ties():
    sql = 'SELECT r."sensor_id" AS room, SUM(r."volume_l") AS amount FROM "public"."samples" AS r GROUP BY 1 ORDER BY amount FETCH NEXT 4 ROWS WITH TIES;'
    expected = {
        "source": "samples",
        "group": "sensor_id",
        "measure": "total",
        "field": "volume_l",
        "direction": "bottom",
        "number": "4",
        "ties": "",
    }
    assert ranking_fields(sql, "List the 4 smallest totals by sensor.") == expected
    assert (
        ranking_fields(
            sql.replace("BY 1", 'BY r."sensor_id"').replace(
                "BY amount", 'BY SUM(r."volume_l") ASC'
            ),
            "Show the bottom four sensors.",
        )
        == expected
    )


@pytest.mark.parametrize(
    "before,after",
    [
        ("public.", "audit."),
        ("turnstiles", '"Turnstiles"'),
        ("counter_id,", '"counter id",'),
        ("counter_id,", "x.counter_id,"),
        ("counter_id,", "counter__id,"),
        ("visits FROM", "counter_id FROM"),
        ("GROUP BY", "JOIN visits v ON v.id = counter_id GROUP BY"),
        ("GROUP BY", "WHERE active GROUP BY"),
        ("BY counter_id ORDER", "BY counter_id, day ORDER"),
        ("ORDER BY", "HAVING COUNT(*) > 1 ORDER BY"),
        ("BY visits DESC", "BY counter_id DESC"),
        ("DESC LIMIT", "DESC, counter_id LIMIT"),
        ("COUNT(*)", "COUNT(user_id)"),
        ("COUNT(*)", "COUNT(DISTINCT user_id)"),
        ("COUNT(*)", "SUM(x.fee)"),
        ("COUNT(*)", "SUM(counter_id)"),
        ("COUNT(*)", "AVG(fee)"),
        ("DESC LIMIT", "DESC NULLS LAST LIMIT"),
        ("LIMIT 2", "LIMIT 2 OFFSET 1"),
        ("LIMIT 2", ""),
        ("SELECT", "SELECT DISTINCT"),
        ("SELECT", "WITH src AS (SELECT 1) SELECT"),
        ("LIMIT 2", "LIMIT 2; SELECT 1"),
        ("BY counter_id ORDER", "BY something_else ORDER"),
    ],
)
def test_unsupported_queries_never_preselect_a_changed_population(before, after):
    assert ranking_fields(SQL.replace(before, after, 1), QUESTION) is None


@pytest.mark.parametrize(
    "question",
    [
        "Show the busiest counters.",
        "For the last two months, rank counters.",
        "The bottom two counters.",
        "Compare the top 2 and the bottom 2 counters.",
        "Compare the top 2 and top 3 counters.",
        "Show the top 3 counters.",
        "The top 2% of counters.",
        "The top two percent of counters.",
        "The top 2.5 counters.",
        "The top 2,500 counters.",
        "The top two hundred counters.",
        "The twenty two highest visit counts.",
        "The 1.2 highest totals.",
        "Compare the top 2–4.",
        "The top two or three counters.",
        "Show the top two and a half counters.",
        None,
        "x" * 2001,
    ],
)
def test_unconfirmed_cutoffs_cannot_prefill_the_review(question):
    assert ranking_fields(SQL, question) is None


def test_oversized_statements_and_result_caps_never_become_review_hints():
    assert (
        ranking_fields(SQL.replace("LIMIT 2", "LIMIT 1000"), "Top 1000 counters")
        is None
    )
    assert ranking_fields(None, QUESTION) is None
    assert ranking_fields(" " * 4096 + SQL, QUESTION) is None


def test_employee_snapshots_history_and_replays_omit_sql_and_hide_other_owners(world):
    owner, owner_id = world.client("A")
    other, _ = world.client("B")
    saved = world.submit(owner, "Private owner question canary")
    chat_id, request_id = saved["chat"]["id"], saved["request"]["id"]
    assert (
        saved["response"]["sql"] == "" and saved["response"]["tables"] == GOOD["tables"]
    )
    for path in (
        f"/api/v1/chats/{chat_id}/messages",
        f"/api/v1/analysis-requests/{request_id}",
    ):
        response = owner.get(path)
        assert response.status_code == 200 and GOOD["sql"] not in response.text
        denied = other.get(path)
        assert denied.status_code == 404
        assert (
            owner_id not in denied.text
            and "Private owner question canary" not in denied.text
            and GOOD["message"] not in denied.text
        )
    assert other.get("/api/v1/chats").json()["items"] == []
    with world.storage.transaction() as conn:
        assert conn.execute(
            "SELECT response->>'sql' FROM app.visual_results WHERE user_id=%s",
            (owner_id,),
        ).fetchone() == (GOOD["sql"],)


def test_personal_export_preserves_answer_and_exact_values_but_no_generated_sql(
    private_exports,
):
    fixture = private_exports
    owner, owner_id = fixture.client(grant=True)
    fixture.world.submit(owner)
    _, raw, _ = fixture.ready(owner, owner_id)
    assert GOOD["sql"].encode() not in raw
    response = json.loads(raw)["messages"][-1]["response"]
    assert response["sql"] == "" and response["tables"] == GOOD["tables"]
    encoded = json.dumps({**GOOD, "sql": ""})
    assert validated_bytes(encoded) == encoded.encode()
    with pytest.raises(ValueError, match="export_result_invalid"):
        validated_bytes(json.dumps(GOOD))
