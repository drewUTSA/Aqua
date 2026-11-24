import { WorkspaceError } from "../../services/workspaceClient.js";

const encoder = new TextEncoder(), hex = /^[a-f0-9]{64}$/, id = /^[a-z][a-z0-9_-]{0,95}$/;
const owner = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const REPORTS = Object.freeze({
  deposit_portfolio_summary: "retail_deposits", service_case_summary: "customer_service", consumer_pipeline_summary: "consumer_lending",
  commercial_exposure_summary: "commercial_lending", credit_review_summary: "credit_underwriting", servicing_exception_summary: "loan_servicing",
  payment_exception_summary: "payments_operations", liquidity_assumption_summary: "treasury_alm", reconciliation_summary: "finance_accounting",
  fraud_workload_summary: "fraud_security", program_control_inventory: "bsa_aml_sanctions", policy_obligation_inventory: "compliance_legal",
  fiduciary_workload_summary: "wealth_trust", service_health_summary: "operations_it_data", training_completion_summary: "human_resources",
  vendor_review_summary: "third_party_risk", audit_issue_summary: "internal_audit",
});
const require = value => { if (!value) throw new WorkspaceError("invalid_response"); };
const revision = value => typeof value === "string" && hex.test(value);
function keys(value, names) {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(descriptors).length === names.length && names.every(name => Object.hasOwn(descriptors, name) && Object.hasOwn(descriptors[name], "value"));
}
function list(value, min, max) {
  return Array.isArray(value) && value.length >= min && value.length <= max
    && Reflect.ownKeys(value).length === value.length + 1
    && Array.from({ length: value.length }, (_, index) => Object.getOwnPropertyDescriptor(value, index)).every(item => item && Object.hasOwn(item, "value"));
}
const text = (value, max) => typeof value === "string" && value.trim().length > 0 && encoder.encode(value).length <= max
  && !/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\uD800-\uDFFF]/u.test(value);
function bound(value) { require(encoder.encode(JSON.stringify(value)).length <= 32768); return structuredClone(value); }
function envelope(value, names, expectedOwner) {
  require(typeof expectedOwner === "string" && owner.test(expectedOwner) && keys(value, ["schemaVersion", "owner_id", ...names])
    && value.schemaVersion === 1 && value.owner_id === expectedOwner);
}
const flags = value => value.synthetic === true && value.demoOnly === true && value.executionEnabled === false && value.approvalRecorded === false
  && value.jurisdiction === "US" && value.currency === "USD";

export function decodeBankContext(value, expectedOwner) {
  envelope(value, ["context", "reports"], expectedOwner);
  const c = value.context;
  require(keys(c, ["bankName", "persona", "asOf", "sourceRevision", "guidanceRevision", "notice", "scopeSource", "synthetic", "demoOnly", "jurisdiction", "currency", "executionEnabled", "approvalRecorded"])
    && flags(c) && text(c.bankName, 240) && ["none", "teller", "analyst", "manager"].includes(c.persona)
    && c.asOf === "2026-11-16" && revision(c.sourceRevision) && revision(c.guidanceRevision) && text(c.notice, 2048)
    && c.scopeSource === "fixed_fictional_demo_registry_not_bank_identity" && list(value.reports, 0, 17));
  const seen = new Set();
  for (const report of value.reports) {
    require(keys(report, ["id", "label", "department"]) && Object.hasOwn(REPORTS, report.id) && REPORTS[report.id] === report.department
      && !seen.has(report.id) && text(report.label, 240)); seen.add(report.id);
  }
  require(c.persona !== "none" || value.reports.length === 0);
  return bound({ ...c, ownerId: expectedOwner, reports: value.reports });
}

export function decodeBankReport(value, expectedOwner, reportId, context) {
  envelope(value, ["result"], expectedOwner);
  const r = value.result, selected = context?.reports?.find(report => report.id === reportId);
  require(context?.ownerId === expectedOwner && selected && keys(r, ["reportId", "title", "department", "asOf", "sourceRevision", "guidanceRevision", "period", "periodStart", "periodEnd", "periodComplete", "truncated", "currency", "jurisdiction", "synthetic", "demoOnly", "readOnly", "executionEnabled", "approvalRecorded", "definition", "caveats", "columns", "rows", "rowCount", "procedure", "nextSteps"])
    && flags(r) && r.readOnly === true && r.periodComplete === false && r.truncated === false
    && r.reportId === reportId && r.department === selected.department && text(r.title, 240) && r.title === selected.label
    && r.asOf === context.asOf && r.period === "2026-11" && r.periodStart === "2026-11-01" && r.periodEnd === r.asOf
    && revision(r.sourceRevision) && revision(r.guidanceRevision));
  if (r.sourceRevision !== context.sourceRevision || r.guidanceRevision !== context.guidanceRevision) throw new WorkspaceError("conflict", 409);
  require(text(r.definition, 4096) && list(r.caveats, 3, 3) && r.caveats.every(item => text(item, 2048))
    && list(r.columns, 1, 8) && list(r.rows, 1, 12) && Number.isSafeInteger(r.rowCount) && r.rowCount === r.rows.length);
  const columns = new Set();
  for (const column of r.columns) {
    require(keys(column, ["key", "label", "unit"]) && typeof column.key === "string" && id.test(column.key)
      && !columns.has(column.key) && text(column.label, 120) && ["text", "count", "USD"].includes(column.unit)); columns.add(column.key);
  }
  for (const row of r.rows) {
    require(list(row, r.columns.length, r.columns.length));
    row.forEach((cell, index) => {
      require(text(cell, 256));
      if (r.columns[index].unit === "count") require(/^(?:0|[1-9]\d{0,23})$/.test(cell));
      if (r.columns[index].unit === "USD") require(/^-?(?:0|[1-9]\d{0,23})\.\d{2}$/.test(cell));
    });
  }
  const p = r.procedure;
  require(keys(p, ["title", "text", "sourceId", "version", "contentSha256", "fictional"]) && p.fictional === true
    && text(p.title, 240) && text(p.text, 4096) && typeof p.sourceId === "string" && id.test(p.sourceId)
    && typeof p.version === "string" && id.test(p.version) && revision(p.contentSha256) && list(r.nextSteps, 3, 3));
  const steps = ["inspect_definition_and_period", "discuss_with_responsible_reviewer", "consider_separate_review_draft"];
  r.nextSteps.forEach((step, index) => require(keys(step, ["id", "text"]) && step.id === steps[index] && text(step.text, 2048)));
  return bound(r);
}

function calendarDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const date = new Date(value + "T00:00:00Z");
  return Number.isFinite(date.getTime()) && date.toISOString().slice(0, 10) === value;
}

export function validReportRequirements(value) {
  return keys(value, ["source", "period_start", "period_end"])
    && ["fictional_snapshot", "institution_record"].includes(value.source)
    && [value.period_start, value.period_end].every(day => day === null || calendarDate(day))
    && (!value.period_start || !value.period_end || value.period_start <= value.period_end);
}

function unavailableReason(requirements, start, end) {
  if (requirements.source === "institution_record") return "institution_source_unavailable";
  if (!requirements.period_start || !requirements.period_end) return "period_required";
  return requirements.period_start === start && requirements.period_end === end ? null : "period_unavailable";
}

export function decodeRequestedReport(value, expectedOwner, reportId, context, requirements) {
  if (value && Object.hasOwn(value, "unavailable")) {
    envelope(value, ["unavailable"], expectedOwner);
    const limit = value.unavailable;
    require(validReportRequirements(requirements) && context?.ownerId === expectedOwner && context.reports.some(item => item.id === reportId)
      && keys(limit, ["reason", "reportId", "sourceRevision", "periodStart", "periodEnd"])
      && limit.reportId === reportId && limit.sourceRevision === context.sourceRevision
      && limit.periodStart === "2026-11-01" && limit.periodEnd === context.asOf
      && typeof limit.reason === "string" && limit.reason === unavailableReason(requirements, limit.periodStart, limit.periodEnd));
    return { unavailable: bound(limit) };
  }
  const report = decodeBankReport(value, expectedOwner, reportId, context);
  if (requirements !== undefined) {
    require(validReportRequirements(requirements) && unavailableReason(requirements, report.periodStart, report.periodEnd) === null);
  }
  return report;
}

const resultFields = {
  simple_interest: ["interest_usd", "principal_plus_interest_usd", "term_months"],
  simple_interest_actual_days: ["interest_usd", "principal_plus_interest_usd", "elapsed_days", "day_count_basis", "year_fraction"],
  amortizing_loan_payment: ["scheduled_monthly_payment_usd", "first_payment_usd", "final_payment_usd", "total_principal_usd", "total_interest_usd",
    "total_payments_usd", "remaining_balance_usd", "requested_term_months", "months_elapsed", "paid_off_early", "final_payment_adjusted"],
  percent_change: ["difference_usd", "percent_change", "period"],
  liquidity_coverage: ["coverage_ratio", "surplus_or_shortfall_usd", "covers_stated_outflows", "period"],
  reconciliation: ["expected_closing_balance_usd", "reported_closing_balance_usd", "reported_less_expected_usd", "balanced", "period"],
};
function resultCell(key, value, inputs) {
  if (["balanced", "covers_stated_outflows", "paid_off_early", "final_payment_adjusted"].includes(key)) return typeof value === "boolean";
  if (typeof value !== "string" || value.length > 48) return false;
  if (key.endsWith("_usd")) return /^-?(?:0|[1-9]\d*)\.\d{2}$/.test(value);
  if (key === "coverage_ratio" || key === "percent_change") return /^-?(?:0|[1-9]\d*)\.\d{6}$/.test(value);
  if (key === "year_fraction") return value === inputs.elapsed_days + "/" + (inputs.day_count_basis === "Actual/360" ? "360" : "365");
  if (key === "requested_term_months") return value === inputs.term_months;
  if (key === "months_elapsed") return /^[1-9]\d{0,2}$/.test(value) && Number(value) <= Number(inputs.term_months);
  return Object.hasOwn(inputs, key) && value === inputs[key];
}

export function decodeCalculation(value, expectedOwner, context, draft) {
  const operation = draft.operation;
  require(context?.ownerId === expectedOwner && context.sourceRevision === draft.expected_source_revision);
  if (Object.hasOwn(value, "unavailable")) {
    envelope(value, ["unavailable"], expectedOwner);
    const limit = value.unavailable;
    require(keys(limit, ["operation", "reason"]) && limit.operation === operation && typeof limit.reason === "string"
      && /^finance_[a-z_]{1,50}$/.test(limit.reason));
    return { unavailable: limit.reason };
  }
  envelope(value, ["calculation"], expectedOwner);
  const c = value.calculation;
  require(keys(c, ["operation", "currency", "inputs", "result", "explanation", "assumptions", "source", "sourceRevision", "synthetic", "executionEnabled", "bankQuote", "approvalRecorded"])
    && c.operation === operation && c.currency === "USD" && c.sourceRevision === draft.expected_source_revision && c.synthetic === true
    && c.executionEnabled === false && c.bankQuote === false && c.approvalRecorded === false && text(c.explanation, 1500)
    && list(c.assumptions, 1, 12) && c.assumptions.every(x => text(x, 1500))
    && keys(c.inputs, Object.keys(draft.confirmedInputs)) && Object.entries(draft.confirmedInputs).every(([key, input]) => c.inputs[key] === input));
  if (!draft.report) require(keys(c.source, ["kind"]) && c.source.kind === "employee_supplied");
  else {
    const r = draft.report, s = c.source;
    require(keys(s, ["kind", "reportId", "title", "row", "rowLabels", "field", "periodStart", "periodEnd", "sourceRevision"])
      && s.kind === "fictional_report" && s.reportId === r.report_id && s.row === r.row && s.field === r.field && s.periodStart === r.period_start
      && s.periodEnd === r.period_end && s.sourceRevision === c.sourceRevision && s.title === draft.reportTitle
      && keys(s.rowLabels, Object.keys(draft.rowLabels)) && Object.entries(draft.rowLabels).every(([key, cell]) => s.rowLabels[key] === cell));
  }
  require(Object.hasOwn(resultFields, operation) && keys(c.result, resultFields[operation])
    && Object.entries(c.result).every(([key, cell]) => resultCell(key, cell, c.inputs)));
  return bound(c);
}
