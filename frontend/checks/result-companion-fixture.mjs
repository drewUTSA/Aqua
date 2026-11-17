// Independently authored saved-result fixture; no query/provider or evaluation packet.
import { normalizeResponse } from "../src/services/apiClient.js";
import { workspaceResultMetadata } from "../src/services/workspaceResultMetadata.js";
import { resultBinding } from "../src/features/resultCompanion/binding.js";
import { RESULT_CHECKS } from "../src/features/resultCompanion/contract.js";

export const IDS = Object.freeze({ owner: "31000000-0000-4000-8000-000000000001", chat: "31000000-0000-4000-8000-000000000002",
  message: "31000000-0000-4000-8000-000000000003", input: "31000000-0000-4000-8000-000000000004", request: "31000000-0000-4000-8000-000000000005" });
export function resultFixture({ legacy = false, empty = false } = {}) {
  const question = "Which saved sample values were returned?";
  const rows = empty ? [] : [{ value: Number("9007199254740993.01"), tag: "1000" }, { value: -1e-10, tag: "NULL" }, { value: null, tag: "" }, { value: -1e-10, tag: "last" }];
  const raw = { status: "success", message: "Saved sample answer.", sql: "/* independent saved fixture */", visualizations: [], kpis: [],
    tables: [{ id: "result", title: "Saved sample", columns: [{ key: "value", label: "Sample value", type: "currency" }, { key: "tag", label: "Tag", type: "string" }], rows }] };
  const metadata = { version: 1, source: { id: "a".repeat(64), freshness_at: null }, generated_at: "2026-11-17T18:00:00Z", filters: null,
    truncated: !empty, max_rows: 1000, aggregation: "unknown", column_units: { value: null, tag: null }, exact_values: empty ? []
      : [{ row: 0, column: "value", value: "9007199254740993.01", kind: "decimal" }, { row: 1, column: "value", value: "-0.0000000001", kind: "decimal" }, { row: 3, column: "value", value: "-0.0000000001", kind: "decimal" }] };
  const response = workspaceResultMetadata(normalizeResponse(raw), legacy ? undefined : metadata);
  const message = { id: IDS.message, requestId: IDS.request, conversationId: IDS.chat, replyTo: IDS.input, sequence: 2, role: "aqua", status: "complete", historical: true, resultUnavailable: false, response };
  const chat = { durable: true, activeConversationId: IDS.chat, active: { historyLoading: false, analyses: { [IDS.request]: { version: 7, state: "complete" } } },
    messages: [{ id: IDS.input, requestId: IDS.request, role: "user", content: question }, message] };
  const binding = resultBinding(chat, IDS.owner, IDS.message, true);
  const checkIds = [...(!legacy && !empty ? ["returned_subset"] : []), ...(!empty ? ["missing_values"] : []), "units_unknown", "freshness_unknown", "scope_unknown", ...(legacy ? ["precision_unverified"] : [])];
  const reply = { schemaVersion: 1, owner_id: IDS.owner, chat_id: IDS.chat, request_id: IDS.request, assistant_message_id: IDS.message, job_version: 7,
    brief: { method: "saved_result_rules", status: legacy ? "limited" : "ready", question,
      source: legacy ? { id: null, generated_at: null, freshness_at: null } : { id: metadata.source.id, generated_at: metadata.generated_at, freshness_at: null },
      scope: { basis: "returned_rows_only", truncated: legacy ? null : !empty, max_rows: legacy ? null : 1000, filters: "unknown", aggregation: "unknown", precision: legacy ? "legacy_unverified" : "sidecar_preferred" },
      field: { index: 0, key: "value", label: "Sample value", kind: empty ? "empty" : "numeric", unit: null },
      counts: { returned_rows: empty ? 0 : 4, missing_values: empty ? 0 : 1, non_missing_values: empty ? 0 : 3 },
      numeric: legacy || empty ? null : { minimum: { value: "-0.0000000001", ties: 2, witness_rows: [1, 3] }, maximum: { value: "9007199254740993.01", ties: 1, witness_rows: [0] } },
      checks: checkIds.map(id => ({ id, text: RESULT_CHECKS[id] })), followup_intents: ["verify_scope", ...(!empty ? ["missing_values"] : []), ...(!legacy && !empty ? ["compare_field"] : [])], execution_enabled: false } };
  return { raw, metadata, chat, message, binding, reply };
}
