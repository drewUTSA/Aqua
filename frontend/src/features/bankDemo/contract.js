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
