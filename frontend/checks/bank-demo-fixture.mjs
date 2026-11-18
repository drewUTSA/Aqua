export const ownerId = "10000000-0000-4000-8000-000000000001";
export const option = { id: "deposit_portfolio_summary", label: "Branch and deposits", department: "retail_deposits" };
export const contextEnvelope = () => ({ schemaVersion: 1, owner_id: ownerId, context: {
  bankName: "Aqua fictional example", persona: "teller", asOf: "2026-11-16", sourceRevision: "a".repeat(64), guidanceRevision: "b".repeat(64),
  notice: "Original fictional data. No real bank is connected.", scopeSource: "fixed_fictional_demo_registry_not_bank_identity",
  synthetic: true, demoOnly: true, jurisdiction: "US", currency: "USD", executionEnabled: false, approvalRecorded: false,
}, reports: [{ ...option }] });
export const reportEnvelope = () => ({ schemaVersion: 1, owner_id: ownerId, result: {
  reportId: option.id, title: option.label, department: option.department, asOf: "2026-11-16", sourceRevision: "a".repeat(64), guidanceRevision: "b".repeat(64),
  period: "2026-11", periodStart: "2026-11-01", periodEnd: "2026-11-16", periodComplete: false, truncated: false,
  currency: "USD", jurisdiction: "US", synthetic: true, demoOnly: true, readOnly: true, executionEnabled: false, approvalRecorded: false,
  definition: "Original fictional deposit buckets, not customer accounts.", caveats: ["Fictional figures.", "Partial snapshot.", "Review definitions."],
  columns: [{ key: "branch", label: "Branch", unit: "text" }, { key: "accounts", label: "Accounts", unit: "count" }, { key: "closing_balance_usd", label: "Closing balance", unit: "USD" }],
  rows: [["north", "1200", "1461250.00"]], rowCount: 1,
  procedure: { title: "Fictional deposit review", text: "Review the original demonstration definition.", sourceId: "deposit_help", version: "fictional-demo-v1", contentSha256: "c".repeat(64), fictional: true },
  nextSteps: [{ id: "inspect_definition_and_period", text: "Review the partial period." }, { id: "discuss_with_responsible_reviewer", text: "Discuss with the human reviewer." }, { id: "consider_separate_review_draft", text: "A separate explicitly requested draft remains unapproved." }],
} });
