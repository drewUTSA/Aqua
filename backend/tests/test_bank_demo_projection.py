"""Web output preserves the existing fictional truth and removes unused data."""

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from eval.banking.catalog import REPORTS
from mcp_demo import reports, web
from mcp_demo.protocol import actor_for


@pytest.mark.parametrize(
    "persona,count", [("none", 0), ("teller", 2), ("analyst", 4), ("manager", 17)]
)
def test_projection_menu_uses_only_canonical_host_grants(persona, count):
    actor = actor_for(persona)
    value = web.context(actor)
    assert len(value["reports"]) == count
    assert {item["id"] for item in value["reports"]} == set(actor.scope.report_ids)
    assert (
        value["context"]["scopeSource"]
        == "fixed_fictional_demo_registry_not_bank_identity"
    )
    assert value["context"]["synthetic"] is True
    assert value["context"]["executionEnabled"] is False
    assert value["context"]["approvalRecorded"] is False


def test_all_seventeen_reports_preserve_exact_values_units_and_canonical_briefs():
    actor = actor_for("manager")
    menu = {v["id"]: v for v in web.context(actor)["reports"]}
    for report_id in REPORTS:
        original = reports.run_report(actor, report_id)
        result = web.report(actor, report_id)
        assert result["title"] == menu[report_id]["label"]
        assert result["department"] == menu[report_id]["department"]
        assert result["rowCount"] == len(original["rows"]) == len(result["rows"])
        assert result["definition"] == original["metric_definition"]
        assert result["caveats"] == original["companion_brief"]["caveats"]
        assert (
            result["procedure"]["text"]
            == original["companion_brief"]["procedure"]["text"]
        )
        assert result["nextSteps"] == [
            {"id": step["id"], "text": step["text"]}
            for step in original["companion_brief"]["next_steps"]
        ]
        for index, row in enumerate(original["rows"]):
            assert result["rows"][index] == [
                str(row[column["key"]]) for column in result["columns"]
            ]
            for column in result["columns"]:
                if column["unit"] == "count":
                    assert type(row[column["key"]]) is int
                elif column["unit"] == "USD":
                    assert column["key"] in web.MONEY_COLUMNS
                    assert type(row[column["key"]]) is str
                else:
                    assert (
                        column["unit"] == "text" and column["key"] in web.TEXT_COLUMNS
                    )
        raw = json.dumps(
            {
                "schemaVersion": 1,
                "owner_id": "33333333-3333-4333-8333-333333333333",
                "result": result,
            }
        )
        assert len(raw.encode()) < 32768
        assert not {
            "monthly_series",
            "scope",
            "tenant_id",
            "principal_id",
            "source_url",
        } & set(result)
        assert result["periodComplete"] is False and result["periodEnd"] == "2026-11-16"
        assert result["readOnly"] is True and result["executionEnabled"] is False


def test_known_deposit_values_remain_exact_and_no_role_prompt_can_change_scope():
    result = web.report(actor_for("teller"), "deposit_portfolio_summary")
    assert result["rows"][0] == ["north", "checking", "1200", "1461250.00"]
    assert sum(int(row[2]) for row in result["rows"]) == 6050
    with pytest.raises(ValueError):
        web.report(actor_for("teller"), "reconciliation_summary")
    with pytest.raises(ValueError):
        web.context(replace(actor_for("teller"), persona="manager"))


@pytest.mark.parametrize(
    "attack",
    [
        "unknown_column",
        "float_count",
        "money_float",
        "count_bool",
        "rows_overflow",
        "wrong_count",
        "wrong_period",
        "executable",
    ],
)
def test_projection_rejects_changed_source_shape_instead_of_guessing_units(
    monkeypatch, attack
):
    original = deepcopy(
        reports.run_report(actor_for("manager"), "deposit_portfolio_summary")
    )
    if attack == "unknown_column":
        for row in original["rows"]:
            row["unreviewed_field"] = "secret"
    elif attack == "float_count":
        original["rows"][0]["accounts"] = 1200.0
    elif attack == "money_float":
        original["rows"][0]["closing_balance_usd"] = 1461250.00
    elif attack == "count_bool":
        original["rows"][0]["accounts"] = True
    elif attack == "rows_overflow":
        original["rows"] *= 2
        original["row_count"] = len(original["rows"])
    elif attack == "wrong_count":
        original["row_count"] = 1
    elif attack == "wrong_period":
        original["period_end"] = "2026-11-30"
    else:
        original["companion_brief"]["execution_enabled"] = True
    monkeypatch.setattr(reports, "run_report", lambda *args: original)
    with pytest.raises(ValueError):
        web.report(actor_for("manager"), "deposit_portfolio_summary")
