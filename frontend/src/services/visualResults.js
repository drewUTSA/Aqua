import { validatePresentation, validateVisualTable } from "./presentationContract.js";

// This hint only starts a placeholder. A saved server descriptor decides which
// completed result can replace it; explanation and negation never request one.
export function visualIntent(question, previous = false) {
  let task = question.trim();
  // Keep this bounded prefix grammar aligned with the server intent classifier.
  for (let index = 0; index < 3; index += 1) task = task.replace(/^(?:(?:please|kindly)\s+|(?:can|could|would|will)\s+you\s+)/i, "");
  if (/\b(?:no|without|don't|do not|not)\s+(?:(?:want|need)\s+(?:to\s+)?)?(?:(?:show|draw|create|render|display|make|include|use|see)\s+)?(?:(?:me|us)\s+)?(?:(?:a|an|any|the)\s+)?(?:charts?|plots?|graphs?|visuali[sz](?:e|ations?))\b/i.test(task)
    || /^(?:(?:and|also|now)\s+)?(?:explain|describe|summarize|why|define|what (?:does|is|are)|tell me about)\b/i.test(task)) return "text";
  if (/\b(?:charts?|plots?|graphs?|visuali[sz](?:e|ation|ations))\b/i.test(task)) return "explicit";
  return previous && /^(?:and|also|now|instead|only|same|filter|group|change|switch|use|for|by|what about)\b/i.test(task)
    && /\b(?:by|per|group|filter|only|last|next|year|month|week|day|quarter|region|categor(?:y|ies)|country|amount|revenue|count|top|bottom|same|instead|compare)\b/i.test(task) ? "followup" : "text";
}

// A compatibility token for legacy, local demo data only; never an auth key.
function legacyKey(value) {
  let hash = 2166136261;
  for (const character of JSON.stringify(value)) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619);
  return (hash >>> 0).toString(16).padStart(8, "0").repeat(8);
}

/** Derive a view without retaining a second cache of private result payloads. */
export function visualResult(message, messages) {
  const response = message?.response;
  if (!response || response.status !== "success" || message.resultUnavailable || !Array.isArray(response.tables) || !response.tables.length) return null;
  const table = response.tables[0];
  if (!table || typeof table !== "object" || Array.isArray(table)) return null;
  const input = messages.find((item) => item.id === message.replyTo)?.content;
  const question = typeof input === "string" && input ? input : typeof table.title === "string" && table.title ? table.title : "Result";
  if (response.presentation !== undefined) return { response, table, descriptor: response.presentation?.charts?.[0] || null,
    intent: response.presentation?.intent || visualIntent(question), reason: response.presentation?.reason || "unsupported_shape", question };
  // P07 history and explicit demo responses keep their table/export. Only the
  // small legacy bar/line vocabulary can be upgraded; no chart config crosses.
  const old = Array.isArray(response.visualizations) ? response.visualizations.find((item) => item && typeof item === "object" && ["bar", "line", "area"].includes(item.type)) : null;
  const intent = visualIntent(question);
  if (!old || response.precisionNote || response.resultMetadata?.exact_values?.length) return { response, table, descriptor: null, intent, reason: "unsupported_shape", question };
  const chartTable = { ...table, id: "result" };
  try {
    validateVisualTable(chartTable);
    if (old.title !== undefined && typeof old.title !== "string" || old.series !== undefined && (!Array.isArray(old.series) || old.series.length !== 1)) throw new Error("presentation_invalid");
    const key = old.xKey, y = old.series?.[0]?.key || old.yKey, label = old.series?.[0]?.label ?? y;
    if (typeof key !== "string" || typeof y !== "string" || typeof label !== "string") throw new Error("presentation_invalid");
    const descriptor = { id: "result-chart", type: old.type === "bar" ? "bar" : "line", title: (old.title || question).slice(0, 160), tableId: "result",
      x: { keys: [key], kind: "category", timezone: null, calendar_parts: [] },
      series: [{ key: y, label: label.slice(0, 80), unit: null }],
      row_indices: table.rows.map((_, index) => index), missing: "gap", reduction: "none", input_rows: table.rows.length,
      output_points: table.rows.length, downsampled: false, approximate: false,
      compatibility_key: legacyKey([typeof response.sql === "string" ? response.sql : "", key, y, table.rows.map((row) => row[key])]), };
    validatePresentation({ version: 1, intent: "explicit", default_view: "chart", reason: "requested_visual", charts: [descriptor] }, { ...response, tables: [chartTable] });
    return { response, table: chartTable, descriptor, intent, reason: "requested_visual", question };
  } catch (error) {
    if (error.message !== "presentation_invalid") throw error;
    return { response, table, descriptor: null, intent, reason: "unsupported_shape", question };
  }
}

export const visualToken = (message) => `${message.id}:${message.requestId || ""}:${message.response?.status || ""}`;
export const emptyVisualView = () => ({ selected: null, open: false, tab: "conversation", mode: "chart", expanded: false, pending: null, failed: null });

export function matchingVisualReply(pending, messages, analyses = {}) {
  if (!pending) return null;
  const request = Object.values(analyses).find((item) => pending.userId === `local-${item.clientId}`);
  const input = messages.find((item) => item.role === "user" && (item.id === pending.userId
    || item.sequence > pending.floor && item.content === pending.question));
  return messages.find((item) => item.role === "aqua" && !pending.seen.includes(visualToken(item))
    && (request ? item.requestId === request.id : pending.retryId ? item.id === pending.retryId || item.replyTo === pending.retryInput && item.sequence > pending.floor : input && item.replyTo === input.id)) || null;
}

export function finishVisualView(view, message, result) {
  if (!view.pending || view.pending.seen.includes(visualToken(message))) return view;
  const pending = view.pending;
  if (message.response?.status === "loading" || message.status === "pending") return view;
  if (message.response?.status !== "success") return { ...view, pending: null, failed: pending.intent !== "text" ? message.id : null };
  if (!result || result.intent === "text") return { ...view, pending: null, failed: null, open: view.selected ? view.open : false };
  // Follow-ups update only a still-open pane. Dismissal during a held request
  // wins over its completion; an earlier reply cannot reclaim the selection.
  return { ...view, selected: message.id, pending: null, failed: null,
    open: pending.dismissed ? false : result.intent === "explicit" || view.open,
    mode: result.descriptor ? view.mode : "table" };
}
