"""SDK-free least-data web projection of the original fictional report truth."""

import re

from eval.banking.catalog import REPORTS
from mcp_demo import data, guidance, reports
from mcp_demo.protocol import canonical, require, require_actor

SOURCE_REVISION = data.SOURCE_REVISION
REPORT_IDS = frozenset(REPORTS)
TEXT_COLUMNS = {
    "branch": "Branch",
    "product": "Product",
    "status": "Status",
    "priority": "Priority",
    "segment": "Segment",
    "stage": "Stage",
    "review_status": "Review status",
    "rail": "Rail",
    "scenario_measure": "Scenario measure",
    "team": "Team",
    "risk": "Declared risk",
    "severity": "Severity",
}
COUNT_COLUMNS = {
    "accounts": "Accounts",
    "case_count": "Cases",
    "overdue_open_count": "Overdue open",
    "loan_count": "Loans",
    "overdue_review_count": "Overdue reviews",
    "exception_count": "Exceptions",
    "control_count": "Controls",
    "service_count": "Services",
    "active_incident_count": "Active incidents",
    "assigned_enrollments": "Assigned enrollments",
    "completed_enrollments": "Completed enrollments",
    "overdue_enrollments": "Overdue enrollments",
    "vendor_count": "Vendors",
    "issue_count": "Issues",
}
MONEY_COLUMNS = {
    "closing_balance_usd": "Closing balance",
    "requested_usd": "Requested amount",
    "outstanding_usd": "Outstanding principal",
    "held_amount_usd": "Held amount",
    "amount_usd": "Amount",
    "opening_usd": "Opening balance",
    "posted_credits_usd": "Posted credits",
    "posted_debits_usd": "Posted debits",
    "calculated_closing_usd": "Calculated closing",
    "statement_closing_usd": "Statement closing",
    "difference_usd": "Difference",
}


def _text(value, maximum=2048):
    require(
        type(value) is str
        and 0 < len(value.encode("utf-8")) <= maximum
        and not any(ord(c) < 32 or ord(c) == 127 for c in value),
        "demo_web_text_invalid",
    )
    return value


def _facts():
    return {
        "asOf": data.AS_OF,
        "sourceRevision": data.SOURCE_REVISION,
        "guidanceRevision": guidance.GUIDANCE_REVISION,
        "synthetic": True,
        "demoOnly": True,
        "jurisdiction": "US",
        "currency": data.CURRENCY,
        "executionEnabled": False,
        "approvalRecorded": False,
    }


def context(actor):
    require_actor(actor)
    return {
        "context": {
            **_facts(),
            "bankName": "Aqua fictional bank demo",
            "persona": actor.persona,
            "scopeSource": "fixed_fictional_demo_registry_not_bank_identity",
            "notice": "All bank figures and procedures are fictional. No bank account is connected; this demo cannot approve or execute actions.",
        },
        "reports": [
            {
                "id": row["report_id"],
                "label": row["title"],
                "department": row["department"],
            }
            for row in reports.authorized_reports(actor)
        ],
    }


def _column(key):
    for values, unit in (
        (TEXT_COLUMNS, "text"),
        (COUNT_COLUMNS, "count"),
        (MONEY_COLUMNS, "USD"),
    ):
        if key in values:
            return {"key": key, "label": values[key], "unit": unit}
    raise ValueError("demo_web_column_invalid")


def _cell(value, unit):
    if unit == "count":
        require(
            type(value) is int and 0 <= value <= 9007199254740991,
            "demo_web_count_invalid",
        )
        return str(value)
    value = _text(value, 256)
    if unit == "USD":
        require(
            re.fullmatch(r"-?(?:0|[1-9][0-9]{0,17})\.[0-9]{2}", value),
            "demo_web_money_invalid",
        )
    return value


def report(actor, report_id):
    """Read and scope-check once in the original core; never recompute a metric."""
    original = reports.run_report(actor, report_id)
    brief = original["companion_brief"]
    require(
        brief["source_revision"] == data.SOURCE_REVISION
        and brief["guidance_revision"] == guidance.GUIDANCE_REVISION
        and brief["report_id"] == report_id
        and brief["execution_enabled"] is False
        and brief["approval_recorded"] is False
        and brief["bank_authentication"] is False,
        "demo_web_source_changed",
    )
    rows = original["rows"]
    require(
        type(rows) is list
        and 1 <= len(rows) <= 12
        and type(original["row_count"]) is int
        and original["row_count"] == len(rows),
        "demo_web_rows_invalid",
    )
    keys = tuple(rows[0])
    require(
        1 <= len(keys) <= 8 and all(tuple(row) == keys for row in rows),
        "demo_web_rows_invalid",
    )
    columns = [_column(key) for key in keys]
    procedure, steps = brief["procedure"], brief["next_steps"]
    require(
        procedure["fictional_policy"] is True
        and procedure["synthetic"] is True
        and procedure["execution_enabled"] is False
        and len(steps) == 3
        and all(step["execution_enabled"] is False for step in steps)
        and len(brief["caveats"]) == 3,
        "demo_web_procedure_invalid",
    )
    citation = procedure["citation"]
    result = {
        **_facts(),
        "reportId": report_id,
        "title": reports.LABELS[REPORTS[report_id]],
        "department": original["department"],
        "period": original["period"],
        "periodStart": original["period_start"],
        "periodEnd": original["period_end"],
        "periodComplete": original["period_complete"],
        "truncated": original["truncated"],
        "readOnly": original["read_only"],
        "definition": _text(original["metric_definition"]),
        "columns": columns,
        "rows": [
            [_cell(row[column["key"]], column["unit"]) for column in columns]
            for row in rows
        ],
        "rowCount": original["row_count"],
        "caveats": [_text(value) for value in brief["caveats"]],
        "procedure": {
            "title": _text(procedure["title"], 160),
            "text": _text(procedure["text"]),
            "sourceId": citation["source_id"],
            "version": citation["document_version"],
            "contentSha256": citation["content_sha256"],
            "fictional": True,
        },
        "nextSteps": [
            {"id": step["id"], "text": _text(step["text"])} for step in steps
        ],
    }
    require(
        result["periodComplete"] is False
        and result["truncated"] is False
        and result["readOnly"] is True
        and result["period"] == "2026-11"
        and result["periodStart"] == "2026-11-01"
        and result["periodEnd"] == data.AS_OF
        and len(canonical(result)) <= 32000,
        "demo_web_output_budget",
    )
    return result
