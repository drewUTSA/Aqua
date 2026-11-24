// Employee inputs use the same field names, units and string encodings as the finance MCP.
const loan = ["principal_usd", "annual_rate_percent"];
export const operations = {
  simple_interest: ["Simple interest · whole months", [...loan, "term_months"]],
  simple_interest_actual_days: ["Simple interest · actual days", [...loan, "elapsed_days", "day_count_basis"]],
  amortizing_loan_payment: ["Monthly loan payment", [...loan, "term_months"]],
  percent_change: ["Percentage change", ["previous_usd", "current_usd", "period"]],
  liquidity_coverage: ["Cash coverage", ["available_liquidity_usd", "projected_outflows_usd", "period"]],
  reconciliation: ["Reconcile a statement", ["opening_balance_usd", "credits_usd", "debits_usd", "reported_closing_balance_usd", "period"]],
};
export const labels = {
  principal_usd: "Principal (USD)", annual_rate_percent: "Annual rate (%)", term_months: "Whole months",
  elapsed_days: "Elapsed days", day_count_basis: "Day-count basis", period: "Shared period",
  previous_usd: "Earlier amount (USD)", current_usd: "Later amount (USD)", available_liquidity_usd: "Available cash (USD)",
  projected_outflows_usd: "Projected outflows (USD)", opening_balance_usd: "Opening balance (USD)", credits_usd: "Credits (USD)",
  debits_usd: "Debits (USD)", reported_closing_balance_usd: "Statement closing balance (USD)",
};
export const choices = { period: ["day", "month", "quarter", "year", "statement"], day_count_basis: ["Actual/360", "Actual/365 Fixed"] };
const balances = { opening_balance_usd: "opening_usd", credits_usd: "posted_credits_usd", debits_usd: "posted_debits_usd", reported_closing_balance_usd: "statement_closing_usd" };
export function fieldsFromReport(operation, report) {
  if (!report) return [];
  if (["consumer_pipeline_summary", "commercial_exposure_summary"].includes(report.reportId) && operations[operation][1].includes("principal_usd"))
    return [["requested_usd", "Requested amount"], ["outstanding_usd", "Outstanding principal"]];
  if (operation === "reconciliation" && report.reportId === "reconciliation_summary")
    return [["reconciliation_balances", "Opening, credits, debits and statement closing"]];
  return [];
}
export function reportValues(report, row, field) {
  const columns = field === "reconciliation_balances" ? balances : { principal_usd: field };
  const result = {};
  for (const [operand, key] of Object.entries(columns)) {
    const index = report.columns.findIndex(column => column.key === key && column.unit === "USD");
    if (index < 0 || !report.rows[row]) throw Error("unavailable_report_value");
    result[operand] = report.rows[row][index];
  }
  return result;
}
export function rowLabel(report, row) {
  return report.columns.flatMap((column, i) => column.unit === "text" ? [column.label + " · " + report.rows[row][i]] : []).join(", ");
}
export function inputPattern(field) {
  if (field === "elapsed_days" || field === "term_months") return "[1-9][0-9]*";
  if (field === "annual_rate_percent") return "(0|[1-9][0-9]*)(\\.[0-9]{1,6})?";
  const signed = ["current_usd", "opening_balance_usd", "reported_closing_balance_usd"].includes(field);
  return (signed ? "-?" : "") + "(0|[1-9][0-9]*)(\\.[0-9]{1,2})?";
}
