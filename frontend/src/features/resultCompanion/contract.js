import { WorkspaceError } from "../../services/workspaceClient.js";
import { canonicalNumeric, compareExactNumeric, exactCell } from "../../services/precisionCells.js";

const encoder = new TextEncoder(), hex = /^[a-f0-9]{64}$/;
const require = value => { if (!value) throw new WorkspaceError("invalid_response"); };
const integer = (value, low, high) => Number.isSafeInteger(value) && value >= low && value <= high;
function keys(value, names) {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(descriptors).length === names.length && names.every(name => Object.hasOwn(descriptors, name) && Object.hasOwn(descriptors[name], "value"));
}
function list(value, low, high) {
  return Array.isArray(value) && integer(value.length, low, high) && Reflect.ownKeys(value).length === value.length + 1
    && Array.from({ length: value.length }, (_, i) => Object.getOwnPropertyDescriptor(value, i)).every(item => item && Object.hasOwn(item, "value"));
}
function text(value, characters, bytes, multiline = false) {
  return typeof value === "string" && value.length > 0 && encoder.encode(value).length <= bytes && [...value].length <= characters
    && !(multiline ? /[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\uD800-\uDFFF]/u : /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\uD800-\uDFFF]/u).test(value);
}
const timestamp = value => typeof value === "string" && value.length <= 40
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
export const RESULT_CHECKS = Object.freeze({
  returned_subset: "This result is truncated. These checks cover only the returned rows; ask for an aggregate/count or narrower scope before treating the list as complete.",
  missing_values: "Some returned rows have no value in this field. Decide whether missing values should be excluded or shown separately before comparing.",
  units_unknown: "The field unit is unspecified. Confirm its definition and unit before using it for a financial comparison.",
  freshness_unknown: "Source freshness is unavailable. The saved generation time does not establish how current the source data is.",
  scope_unknown: "Filters and aggregation are unspecified. Review the original question and SQL before assuming what one returned row represents.",
  precision_unverified: "This older saved result has no verified precision descriptor. Numeric extrema are unavailable; use its existing table and verify important figures against the source.",
});

function extreme(value, binding, columnIndex, count, nonMissing) {
  require(keys(value, ["value", "ties", "witness_rows"]) && canonicalNumeric(value.value)
    && integer(value.ties, 1, nonMissing) && list(value.witness_rows, 1, Math.min(3, value.ties)));
  let previous = -1;
  for (const index of value.witness_rows) {
    require(integer(index, 0, count - 1) && index > previous); previous = index;
    const row = binding.table.rows[index], key = binding.table.columns[columnIndex].key, cell = row[key];
    require((typeof cell === "number" && Number.isFinite(cell) && (!Number.isInteger(cell) || Number.isSafeInteger(cell))
      || exactCell(binding.table, row, key)) && compareExactNumeric(cell, value.value) === 0);
  }
}

export function decodeResultBrief(value, binding, columnIndex) {
  require(binding && integer(columnIndex, 0, binding.table.columns.length - 1));
  require(keys(value, ["schemaVersion", "owner_id", "chat_id", "request_id", "assistant_message_id", "job_version", "brief"])
    && value.schemaVersion === 1 && value.owner_id === binding.ownerId && value.chat_id === binding.chatId && value.request_id === binding.requestId
    && value.assistant_message_id === binding.messageId && integer(value.job_version, 1, Number.MAX_SAFE_INTEGER)
    && (binding.jobVersion === null || value.job_version === binding.jobVersion));
  const b = value.brief, column = binding.table.columns[columnIndex];
  require(keys(b, ["method", "status", "question", "source", "scope", "field", "counts", "numeric", "checks", "followup_intents", "execution_enabled"])
    && b.method === "saved_result_rules" && ["ready", "limited"].includes(b.status) && b.execution_enabled === false
    && text(b.question, 2000, 8000, true) && (binding.question === null || b.question === binding.question));
  require(keys(b.source, ["id", "generated_at", "freshness_at"]) && b.source.freshness_at === null
    && keys(b.scope, ["basis", "truncated", "max_rows", "filters", "aggregation", "precision"])
    && b.scope.basis === "returned_rows_only" && b.scope.filters === "unknown" && b.scope.aggregation === "unknown");
  require(keys(b.field, ["index", "key", "label", "kind", "unit"]) && b.field.index === columnIndex && b.field.key === column.key
    && text(b.field.key, 256, 1024) && text(b.field.label, 256, 1024) && b.field.label === (typeof column.label === "string" && column.label ? column.label : column.key)
    && ["numeric", "text", "boolean", "mixed", "empty"].includes(b.field.kind) && b.field.unit === null);
  const c = b.counts;
  require(keys(c, ["returned_rows", "missing_values", "non_missing_values"]) && integer(c.returned_rows, 0, 1000)
    && c.returned_rows === binding.table.rows.length && integer(c.missing_values, 0, c.returned_rows) && integer(c.non_missing_values, 0, c.returned_rows)
    && c.missing_values + c.non_missing_values === c.returned_rows && (b.field.kind === "empty") === (c.non_missing_values === 0));
  if (b.status === "ready") {
    const m = binding.metadata;
    require(m?.version === 1 && m.source && typeof b.source.id === "string" && hex.test(b.source.id) && timestamp(b.source.generated_at)
      && b.source.id === m.source.id && b.source.generated_at === m.generated_at && typeof b.scope.truncated === "boolean"
      && b.scope.truncated === m.truncated && b.scope.max_rows === 1000 && b.scope.precision === "sidecar_preferred");
  } else require(binding.metadata === undefined && b.source.id === null && b.source.generated_at === null
    && b.scope.truncated === null && b.scope.max_rows === null && b.scope.precision === "legacy_unverified");
  const numeric = b.status === "ready" && b.field.kind === "numeric" && c.non_missing_values > 0;
  require(numeric ? keys(b.numeric, ["minimum", "maximum"]) : b.numeric === null);
  if (numeric) {
    extreme(b.numeric.minimum, binding, columnIndex, c.returned_rows, c.non_missing_values);
    extreme(b.numeric.maximum, binding, columnIndex, c.returned_rows, c.non_missing_values);
    const comparison = compareExactNumeric(b.numeric.minimum.value, b.numeric.maximum.value);
    require(comparison !== null && comparison <= 0);
    require(comparison === 0 ? b.numeric.minimum.ties === c.non_missing_values && b.numeric.maximum.ties === c.non_missing_values
      : b.numeric.minimum.ties + b.numeric.maximum.ties <= c.non_missing_values);
  }
  const checks = [...(b.scope.truncated === true ? ["returned_subset"] : []), ...(c.missing_values ? ["missing_values"] : []),
    "units_unknown", "freshness_unknown", "scope_unknown", ...(b.status === "limited" ? ["precision_unverified"] : [])];
  require(list(b.checks, checks.length, checks.length));
  b.checks.forEach((check, index) => require(keys(check, ["id", "text"]) && check.id === checks[index] && check.text === RESULT_CHECKS[check.id]));
  const intents = ["verify_scope", ...(c.missing_values ? ["missing_values"] : []), ...(numeric ? ["compare_field"] : [])];
  require(list(b.followup_intents, intents.length, intents.length) && b.followup_intents.every((id, index) => id === intents[index]));
  require(encoder.encode(JSON.stringify(value)).length <= 32768);
  return structuredClone(value);
}
