"""Employee-confirmed illustrations from explicit terms and authorized fictional report cells."""

from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    field_validator,
)

from workspace.errors import WorkspaceError


class ReportValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    report_id: StrictStr = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    row: StrictInt = Field(ge=0, le=99)
    period_start: StrictStr = Field(min_length=10, max_length=10)
    period_end: StrictStr = Field(min_length=10, max_length=10)
    field: Literal["requested_usd", "outstanding_usd", "reconciliation_balances"]


class CalculationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    schemaVersion: StrictInt = Field(ge=1, le=1)
    confirmed: StrictBool
    expected_source_revision: StrictStr = Field(pattern=r"^[a-f0-9]{64}$")
    operation: Literal[
        "simple_interest",
        "simple_interest_actual_days",
        "amortizing_loan_payment",
        "percent_change",
        "liquidity_coverage",
        "reconciliation",
    ]
    currency: Literal["USD"]
    parameters: dict[
        Annotated[StrictStr, Field(min_length=1, max_length=40)],
        Annotated[StrictStr, Field(min_length=1, max_length=24)],
    ] = Field(max_length=5)
    report: ReportValues | None = None

    @field_validator("confirmed")
    @classmethod
    def employee_confirmed(cls, value):
        if not value:
            raise ValueError("bank_demo_confirmation_required")
        return value


RECONCILIATION = {
    "opening_balance_usd": "opening_usd",
    "credits_usd": "posted_credits_usd",
    "debits_usd": "posted_debits_usd",
    "reported_closing_balance_usd": "statement_closing_usd",
}
LENDING = frozenset({"consumer_pipeline_summary", "commercial_exposure_summary"})
LOANS = frozenset(
    {"simple_interest", "simple_interest_actual_days", "amortizing_loan_payment"}
)


def report_inputs(request, source, check):
    reference = request.report
    report = source.report(reference.report_id, request.expected_source_revision, check)
    if (reference.period_start, reference.period_end) != (
        report["periodStart"],
        report["periodEnd"],
    ):
        raise WorkspaceError("revision_conflict", 409)
    if reference.row >= len(report["rows"]):
        raise WorkspaceError("invalid_request", 422)
    if (
        request.operation in LOANS
        and reference.report_id in LENDING
        and reference.field in ("requested_usd", "outstanding_usd")
    ):
        columns = {"principal_usd": reference.field}
    elif (
        request.operation == "reconciliation"
        and reference.report_id == "reconciliation_summary"
        and reference.field == "reconciliation_balances"
        and request.parameters.get("period") == "statement"
    ):
        columns = RECONCILIATION
    else:
        raise WorkspaceError("invalid_request", 422)
    row = dict(
        zip(
            (col["key"] for col in report["columns"]),
            report["rows"][reference.row],
            strict=True,
        )
    )
    money_columns = {col["key"] for col in report["columns"] if col["unit"] == "USD"}
    if (
        not set(columns.values()) <= money_columns
        or columns.keys() & request.parameters.keys()
    ):
        raise WorkspaceError("invalid_request", 422)
    labels = {
        col["label"]: row[col["key"]]
        for col in report["columns"]
        if col["unit"] == "text"
    }
    provenance = {
        "kind": "fictional_report",
        "reportId": reference.report_id,
        "title": report["title"],
        "row": reference.row,
        "rowLabels": labels,
        "field": reference.field,
        "periodStart": report["periodStart"],
        "periodEnd": report["periodEnd"],
        "sourceRevision": report["sourceRevision"],
    }
    return {key: row[name] for key, name in columns.items()}, provenance


def calculate(request, source, check):
    from mcp_demo import finance, web
    from mcp_demo.protocol import actor_for

    actor = actor_for(source.persona)
    if (
        "public_education" not in actor.scope.tool_ids
        or "public_finance" not in actor.scope.object_ids
    ):
        raise WorkspaceError("access_denied", 403)
    if request.expected_source_revision != web.SOURCE_REVISION:
        raise WorkspaceError("revision_conflict", 409)
    supplied = dict(request.parameters)
    if "currency" in supplied:
        raise WorkspaceError("invalid_request", 422)
    provenance = {"kind": "employee_supplied"}
    if request.report:
        values, provenance = report_inputs(request, source, check)
        supplied.update(values)
    check()
    try:
        result = finance.calculate_finance(
            request.operation, {**supplied, "currency": "USD"}
        )
    except finance.FinanceDenied as error:
        # Only locally defined categories reach the employee.
        reason = (
            error.args[0]
            if error.args and error.args[0] in finance.ERRORS
            else "finance_invalid_input"
        )
        return {"unavailable": {"reason": reason, "operation": request.operation}}
    check()
    return {
        "calculation": {
            "operation": request.operation,
            "currency": "USD",
            "inputs": result["inputs"],
            "result": result["result"],
            "explanation": result["explanation"],
            "assumptions": result["assumptions"],
            "source": provenance,
            "sourceRevision": web.SOURCE_REVISION,
            "synthetic": True,
            "executionEnabled": False,
            "bankQuote": False,
            "approvalRecorded": False,
        }
    }
