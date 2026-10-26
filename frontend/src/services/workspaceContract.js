import { normalizeResponse } from "./apiClient.js";

export const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
export const validId = (value) => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const text = (value, maximum) => typeof value === "string" && value.length <= maximum;
const timestamp = (value) => typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));
const revision = (value) => Number.isSafeInteger(value) && value >= 1;
export function requireContract(condition) { if (!condition) throw new Error("workspace_invalid_response"); }

export function chatRecord(value) {
  requireContract(isRecord(value) && validId(value.id) && text(value.title, 240) && revision(value.revision)
    && (value.project_id === null || validId(value.project_id)) && typeof value.archived === "boolean"
    && Number.isSafeInteger(value.message_count) && value.message_count >= 0 && timestamp(value.last_activity_at));
  return { id: value.id, title: value.title, projectId: value.project_id, archived: value.archived, revision: value.revision,
    messageCount: value.message_count, updatedAt: Date.parse(value.last_activity_at) };
}
export function projectRecord(value) {
  requireContract(isRecord(value) && validId(value.id) && text(value.name, 240) && revision(value.revision) && typeof value.archived === "boolean");
  return { id: value.id, name: value.name, archived: value.archived, revision: value.revision };
}
export function promptRecord(value) {
  requireContract(isRecord(value) && validId(value.id) && text(value.label, 240) && text(value.prompt, 4000)
    && typeof value.pinned === "boolean" && revision(value.revision) && Number.isSafeInteger(value.use_count) && value.use_count >= 0);
  return { id: value.id, label: value.label, prompt: value.prompt, pinned: value.pinned, revision: value.revision, useCount: value.use_count };
}
export function messageRecord(value) {
  requireContract(isRecord(value) && validId(value.id) && validId(value.chat_id) && Number.isSafeInteger(value.sequence) && value.sequence >= 1
    && ["user", "aqua"].includes(value.role) && text(value.content, 200000) && validId(value.request_id)
    && (value.reply_to === null || validId(value.reply_to)) && ["pending", "complete", "error", "interrupted"].includes(value.status)
    && typeof value.result_unavailable === "boolean");
  let response = value.result_unavailable || value.response === null ? null : normalizeResponse(value.response);
  if (value.role === "aqua" && !response) response = { status: "error", sql: "", tables: [], visualizations: [], kpis: [], error: {
    code: value.result_unavailable ? "access_denied" : value.status === "pending" ? "pending" : "interrupted",
    message: value.result_unavailable ? "This saved result is unavailable with your current data access."
      : value.status === "pending" ? "This request has not finished. Refresh this chat to check its saved result."
        : "This request did not finish. You can ask a new question.", retryable: false } };
  return { id: value.id, conversationId: value.chat_id, sequence: value.sequence, role: value.role, content: value.role === "aqua" && value.result_unavailable ? "" : value.content,
    requestId: value.request_id, replyTo: value.reply_to, modelId: value.model_id || "", status: value.status,
    response, resultUnavailable: value.result_unavailable, historical: true };
}
export function pageRecord(body, normalize, cursorName = "next_cursor") {
  requireContract(isRecord(body) && Array.isArray(body.items) && body.items.length <= 100
    && (body[cursorName] === null || text(body[cursorName], 4096)));
  return { items: body.items.map(normalize), cursor: body[cursorName] };
}
export function submissionRecord(body) {
  requireContract(isRecord(body) && isRecord(body.request) && validId(body.request.id)
    && validId(body.request.client_request_id) && ["pending", "running", "complete", "error", "interrupted"].includes(body.request.state));
  const chat = chatRecord(body.chat), input = messageRecord(body.input_message), assistant = messageRecord(body.assistant_message);
  requireContract(input.role === "user" && assistant.role === "aqua" && input.conversationId === chat.id && assistant.conversationId === chat.id
    && input.id === body.request.input_message_id && assistant.id === body.request.reply_message_id && assistant.replyTo === input.id
    && assistant.requestId === body.request.id);
  return { chat, input, assistant, request: { id: body.request.id, clientId: body.request.client_request_id, state: body.request.state } };
}
