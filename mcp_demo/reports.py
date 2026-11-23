"""Closed fictional aggregates, derived from one fixture, with no SQL endpoint."""

from collections import defaultdict
from decimal import Context, Decimal, localcontext
import hashlib
import time

from eval.banking.catalog import DEPARTMENTS, REPORTS
from eval.banking.data import encode
from eval.banking.reports import ReportArtifact, validate_artifact
from mcp_demo import guidance
from mcp_demo.data import (
    AS_OF,
    CURRENCY,
    DATA,
    DEMO_TENANT,
    PERIOD,
    SOURCE_REVISION,
    SOURCE_VERSION,
    provenance,
)
from mcp_demo.protocol import canonical, require, require_actor

LABELS = {item.id: item.label for item in DEPARTMENTS}
METRICS = frozenset(
    {"gl_operating_income", "gl_operating_expense", "gl_operating_surplus"}
)
METRIC_DEFINITIONS = {
    "gl_operating_income": "Monthly SUM of fictional interest_income plus fee_income ledger entries; gross specified income, not GAAP net income or deposit flows.",
    "gl_operating_expense": "Monthly SUM of fictional operating_expense ledger entries as positive USD costs; only the defined fixture scope is represented.",
    "gl_operating_surplus": "Fictional monthly interest_income plus fee_income minus operating_expense; excludes taxes, loss provisions and every unmodeled item, so is not GAAP net income.",
}


def money(cents):
    with localcontext(Context(prec=28)):
        return format(Decimal(cents) / 100, ".2f")


def _parameters(period, currency):
    require(type(period) is str and period == PERIOD, "demo_period_unsupported")
    require(type(currency) is str and currency == CURRENCY, "demo_currency_unsupported")


def artifact_for(actor, report_id, now, period=PERIOD, currency=CURRENCY):
    require_actor(actor)
    _parameters(period, currency)
    require(type(report_id) is str and report_id in REPORTS, "demo_report_unknown")
    require(type(now) is int and 0 <= now < 9007199254740691, "demo_clock_invalid")
    key = hashlib.sha256(
        canonical([SOURCE_REVISION, report_id, period, currency])
    ).hexdigest()[:24]
    artifact = ReportArtifact(
        "demo_" + key,
        REPORTS[report_id],
        DEMO_TENANT,
        report_id,
        SOURCE_REVISION,
        SOURCE_VERSION,
        now,
        now + 300,
    )
    validate_artifact(artifact, actor.scope, now)
    return artifact


def authorized_reports(actor):
    require_actor(actor)
    return [
        {
            "report_id": report,
            "department": department,
            "title": LABELS[department],
            "object_id": department,
            "periods": [PERIOD],
            "currency": CURRENCY,
            "synthetic": True,
        }
        for report, department in REPORTS.items()
        if report in actor.scope.report_ids
        and department in actor.scope.object_ids
        and "read_report" in actor.scope.tool_ids
    ]


def _posted(bucket=None):
    return [
        row
        for row in DATA["transactions"]
        if row["status"] == "posted" and (bucket is None or row["bucket_id"] == bucket)
    ]


def _flows(rows):
    return (
        sum(r["amount_cents"] for r in rows if r["direction"] == "deposit"),
        sum(r["amount_cents"] for r in rows if r["direction"] == "withdrawal"),
    )


def _deposits():
    result = []
    for bucket in DATA["deposit_buckets"]:
        credits, debits = _flows(_posted(bucket["id"]))
        result.append(
            {
                "branch": bucket["branch"],
                "product": bucket["product"],
                "accounts": bucket["accounts"],
                "closing_balance_usd": money(
                    bucket["opening_cents"] + credits - debits
                ),
            }
        )
    return result


def _cases(department):
    groups = defaultdict(lambda: [0, 0])
    for case in DATA["cases"]:
        if case["department"] == department:
            bucket = groups[(case["status"], case["priority"])]
            bucket[0] += 1
            bucket[1] += case["status"] != "closed" and case["due"] < AS_OF
    return [
        {
            "status": status,
            "priority": priority,
            "case_count": values[0],
            "overdue_open_count": values[1],
        }
        for (status, priority), values in sorted(groups.items())
    ]


def _loans(segment=None, *, reviews=False):
    groups = defaultdict(lambda: [0, 0, 0, 0])
    for loan in DATA["loans"]:
        if segment is not None and loan["segment"] != segment:
            continue
        label = loan["review_status"] if reviews else loan["stage"]
        bucket = groups[(loan["segment"], label)]
        bucket[0] += 1
        bucket[1] += loan["requested_cents"]
        bucket[2] += loan["outstanding_cents"]
        bucket[3] += loan["review_status"] != "current" and loan["review_due"] < AS_OF
    return [
        {
            "segment": segment,
            "review_status" if reviews else "stage": label,
            "loan_count": values[0],
            "requested_usd": money(values[1]),
            "outstanding_usd": money(values[2]),
            "overdue_review_count": values[3],
        }
        for (segment, label), values in sorted(groups.items())
    ]


def _payments():
    groups = defaultdict(lambda: [0, 0])
    for row in DATA["transactions"]:
        if row["status"] == "exception":
            groups[row["rail"]][0] += 1
            groups[row["rail"]][1] += row["amount_cents"]
    return [
        {"rail": rail, "exception_count": value[0], "held_amount_usd": money(value[1])}
        for rail, value in sorted(groups.items())
    ]


def _liquidity():
    amounts = defaultdict(int)
    for row in DATA["treasury_assumptions"]:
        amounts[row["kind"]] += row["amount_cents"]
    amounts["net_assumed_outflow"] = (
        amounts["assumed_outflow"] - amounts["assumed_inflow"]
    )
    return [
        {"scenario_measure": key, "amount_usd": money(value)}
        for key, value in sorted(amounts.items())
    ]


def _reconciliation():
    result = []
    for observation in DATA["reconciliation_observations"]:
        branch = observation["branch"]
        buckets = [row for row in DATA["deposit_buckets"] if row["branch"] == branch]
        opening = sum(row["opening_cents"] for row in buckets)
        transactions = [
            transaction for row in buckets for transaction in _posted(row["id"])
        ]
        credits, debits = _flows(transactions)
        calculated = opening + credits - debits
        statement = observation["statement_closing_cents"]
        result.append(
            {
                "branch": branch,
                "opening_usd": money(opening),
                "posted_credits_usd": money(credits),
                "posted_debits_usd": money(debits),
                "calculated_closing_usd": money(calculated),
                "statement_closing_usd": money(statement),
                "difference_usd": money(statement - calculated),
            }
        )
    return result


def _controls(department):
    groups = defaultdict(lambda: [0, 0])
    for row in DATA["controls"]:
        if row["department"] == department:
            bucket = groups[row["status"]]
            bucket[0] += 1
            bucket[1] += row["status"] != "documented" and row["due"] < AS_OF
    return [
        {
            "status": status,
            "control_count": values[0],
            "overdue_review_count": values[1],
        }
        for status, values in sorted(groups.items())
    ]


def _health():
    groups = defaultdict(lambda: [0, 0])
    cases = {row["id"]: row for row in DATA["cases"]}
    for row in DATA["services"]:
        bucket = groups[row["status"]]
        bucket[0] += 1
        case = cases.get(row["incident_case_id"])
        bucket[1] += case is not None and case["status"] != "closed"
    return [
        {
            "status": status,
            "service_count": values[0],
            "active_incident_count": values[1],
        }
        for status, values in sorted(groups.items())
    ]


def _training():
    groups = defaultdict(lambda: [0, 0, 0])
    for row in DATA["training_cohorts"]:
        bucket = groups[row["team"]]
        bucket[0] += row["assigned"]
        bucket[1] += row["completed"]
        bucket[2] += row["assigned"] - row["completed"] if row["due"] < AS_OF else 0
    return [
        {
            "team": team,
            "assigned_enrollments": values[0],
            "completed_enrollments": values[1],
            "overdue_enrollments": values[2],
        }
        for team, values in sorted(groups.items())
    ]


def _vendors():
    groups = defaultdict(lambda: [0, 0])
    for row in DATA["vendors"]:
        bucket = groups[(row["risk"], row["review_status"])]
        bucket[0] += 1
        bucket[1] += row["review_status"] != "current" and row["review_due"] < AS_OF
    return [
        {
            "risk": risk,
            "review_status": status,
            "vendor_count": values[0],
            "overdue_review_count": values[1],
        }
        for (risk, status), values in sorted(groups.items())
    ]


def _audit():
    groups = defaultdict(lambda: [0, 0])
    for row in DATA["audit_issues"]:
        bucket = groups[(row["severity"], row["status"])]
        bucket[0] += 1
        bucket[1] += row["status"] != "closed" and row["due"] < AS_OF
    return [
        {
            "severity": severity,
            "status": status,
            "issue_count": values[0],
            "overdue_open_count": values[1],
        }
        for (severity, status), values in sorted(groups.items())
    ]


DEFINITIONS = {
    "deposit_portfolio_summary": "Opening November1 deposit buckets plus posted deposits minus posted withdrawals; exception amounts are excluded. Accounts are fictional bucket counts.",
    "service_case_summary": "Fictional service cases grouped by status/priority; overdue means open and due before November16, not a legal deadline.",
    "consumer_pipeline_summary": "Consumer applications grouped by stage. Requested amounts were applied for. Outstanding amounts are the unpaid principal at the snapshot date. Original disbursements require a separate source.",
    "commercial_exposure_summary": "Commercial loans grouped by stage. Outstanding amounts measure unpaid principal at the snapshot date. Requested amounts may be unfunded. Original disbursements require a separate source.",
    "credit_review_summary": "Manual fictional review labels across loan records; overdue review means non-current and due before November16. These are not credit ratings or lending decisions.",
    "servicing_exception_summary": "Fictional servicing cases grouped by status/priority, linked internally to loan records; no borrower or payment instruction is returned.",
    "payment_exception_summary": "Only unposted exception transactions by rail; held amounts do not change deposit closing balances and are not an instruction to resend payments.",
    "liquidity_assumption_summary": "Fictional liquid-resource and inflow/outflow assumptions; net outflow is assumed outflow minus inflow. No regulatory LCR, solvency assertion or complete balance sheet is implied.",
    "reconciliation_summary": "Branch deposit opening balances plus posted credits minus posted debits, compared with independent fictional statement observations; difference equals statement minus calculated closing. Deposit flows are not revenue.",
    "fraud_workload_summary": "Fictional fraud-team case workload only; labels are neither confirmed fraud nor a customer accusation.",
    "program_control_inventory": "Fictional BSA/AML/sanctions control-document inventory, not actual monitoring, SAR content, sanctions determinations or compliance evidence.",
    "policy_obligation_inventory": "Fictional policy-review tasks by status; no legal interpretation or assurance that a bank meets an obligation.",
    "fiduciary_workload_summary": "Fictional fiduciary review cases by status/priority; no trust assets, beneficiary data or authority to distribute funds.",
    "service_health_summary": "Static fictional service statuses and linked open incident cases; not a live service probe or availability SLO.",
    "training_completion_summary": "Aggregated course enrollments across fictional cohorts; counts are enrollments, not distinct employees. Overdue uses the fictional due dates.",
    "vendor_review_summary": "Fictional vendors grouped by declared review status/risk; overdue reviews are not a completed vendor-risk judgment.",
    "audit_issue_summary": "Fictional audit tracking records by severity/status; open overdue means due before November16. No independent audit assurance is claimed.",
}
READERS = {
    "deposit_portfolio_summary": _deposits,
    "service_case_summary": lambda: _cases("customer_service"),
    "consumer_pipeline_summary": lambda: _loans("consumer"),
    "commercial_exposure_summary": lambda: _loans("commercial"),
    "credit_review_summary": lambda: _loans(reviews=True),
    "servicing_exception_summary": lambda: _cases("loan_servicing"),
    "payment_exception_summary": _payments,
    "liquidity_assumption_summary": _liquidity,
    "reconciliation_summary": _reconciliation,
    "fraud_workload_summary": lambda: _cases("fraud_security"),
    "program_control_inventory": lambda: _controls("bsa_aml_sanctions"),
    "policy_obligation_inventory": lambda: _controls("compliance_legal"),
    "fiduciary_workload_summary": lambda: _cases("wealth_trust"),
    "service_health_summary": _health,
    "training_completion_summary": _training,
    "vendor_review_summary": _vendors,
    "audit_issue_summary": _audit,
}


def _companion_brief(actor, report_id, period, currency):
    _parameters(period, currency)
    procedure = guidance.procedure_for_report(
        actor,
        report_id,
        source_revision=SOURCE_REVISION,
        guidance_revision=guidance.GUIDANCE_REVISION,
        as_of=AS_OF,
    )
    result = {
        "schemaVersion": 1,
        "status": "context_only",
        "report_id": report_id,
        "department": REPORTS[report_id],
        "source_revision": SOURCE_REVISION,
        "source_version": SOURCE_VERSION,
        "guidance_revision": guidance.GUIDANCE_REVISION,
        "as_of": AS_OF,
        "period": period,
        "period_start": "2026-11-01",
        "period_end": AS_OF,
        "period_complete": False,
        "currency": currency,
        "freshness_basis": "fixed_demo_snapshot_not_live_bank_data_or_policy",
        "metric_definition": DEFINITIONS[report_id],
        "caveats": [
            "All figures and procedures are original fictional demo material, not a real bank's records or approved policy.",
            "November1–16,2026 is a partial snapshot; these operational figures do not describe a complete month.",
            "Read the exact metric definition and cited procedure before interpreting a count, amount or review status.",
        ],
        "procedure": procedure,
        "next_steps": [
            {
                "id": "inspect_definition_and_period",
                "text": "Review the definition, partial period and source facts before interpreting these figures.",
                "execution_enabled": False,
            },
            {
                "id": "discuss_with_responsible_reviewer",
                "text": "If the fictional facts need follow-up, discuss the cited procedure and relevant figures with the responsible human reviewer.",
                "execution_enabled": False,
            },
            {
                "id": "consider_separate_review_draft",
                "text": "If you explicitly request it, separate draft preparation can produce an unapproved review proposal; this brief cannot approve or execute it.",
                "requires_explicit_user_request": True,
                "execution_enabled": False,
            },
        ],
        "synthetic": True,
        "data_only": True,
        "instruction_authority": False,
        "bank_authentication": False,
        "approval_recorded": False,
        "execution_enabled": False,
        "model_calls": 0,
    }
    require(len(canonical(result)) <= 8192, "demo_brief_budget")
    return result


def run_report(actor, report_id, period=PERIOD, currency=CURRENCY):
    artifact = artifact_for(actor, report_id, int(time.time()), period, currency)
    rows = READERS[report_id]()
    require(0 < len(rows) <= 12, "demo_report_budget")
    result = {
        **provenance(),
        "report_id": report_id,
        "department": REPORTS[report_id],
        "object_id": artifact.object_id,
        "artifact_id": artifact.artifact_id,
        "period": period,
        "period_start": "2026-11-01",
        "period_end": AS_OF,
        "period_complete": False,
        "truncated": False,
        "read_only": True,
        "metric_definition": DEFINITIONS[report_id],
        "rows": rows,
        "row_count": len(rows),
        "data_only": True,
        "authorization_basis": "fixed_demo_persona_not_bank_authentication",
        "companion_brief": _companion_brief(actor, report_id, period, currency),
    }
    if report_id == "reconciliation_summary":
        result["monthly_series"] = get_monthly_series(actor, "gl_operating_surplus")
    if report_id in {
        "consumer_pipeline_summary",
        "commercial_exposure_summary",
        "credit_review_summary",
    }:
        result["loan_amount_basis"] = {
            "requested_usd": "amount_applied_for",
            "outstanding_usd": "unpaid_principal_at_snapshot",
            "original_disbursement_available": False,
        }
    encode(result)
    return result


def get_monthly_series(actor, metric_id):
    """Trusted fixture-derived rows for a separately qualified existing trend tool."""
    artifact_for(actor, "reconciliation_summary", int(time.time()))
    require(type(metric_id) is str and metric_id in METRICS, "demo_metric_unknown")
    months = defaultdict(lambda: defaultdict(int))
    for row in DATA["monthly_ledger"]:
        if row["complete"]:
            months[row["period"]][row["category"]] += row["amount_cents"]
    points = []
    for period, categories in sorted(months.items()):
        income = categories["interest_income"] + categories["fee_income"]
        expense = categories["operating_expense"]
        value = {
            "gl_operating_income": income,
            "gl_operating_expense": expense,
            "gl_operating_surplus": income - expense,
        }[metric_id]
        points.append({"period": period + "-01", "value": money(value)})
    require(len(points) == 18, "demo_monthly_completeness")
    result = {
        "metric_id": metric_id,
        "definition": METRIC_DEFINITIONS[metric_id],
        "unit": "USD",
        "aggregation": "monthly_sum",
        "complete": True,
        "truncated": False,
        "points": points,
        "dataset_revision": SOURCE_REVISION,
        "as_of": AS_OF,
        "excluded_partial_periods": [PERIOD],
        "source_origin": "Aqua-authored fictional monthly ledger",
        "synthetic": True,
        "complete_for_fixture_scope_only": True,
    }
    return {**result, "source_revision": hashlib.sha256(canonical(result)).hexdigest()}
