import { operationId } from "../services/workspaceClient.js";

export function emptyConversation() {
  const id = `draft-${operationId()}`;
  return { id, viewId: id, title: "New chat", draft: "", messages: [], messageCount: 0, updatedAt: Date.now(),
    projectId: null, archived: false, revision: null, loaded: true, olderCursor: null, operation: null };
}
export function initialWorkspace() {
  const conversation = emptyConversation();
  return { activeId: conversation.id, records: { [conversation.id]: conversation }, deletedChatIds: [], notice: "", loading: false };
}

// This cue offers an optional form. Only employee-selected fields define its query.
export function isOrdinaryRanking(text) {
  if (typeof text !== "string" || /^\s*Rank groups:/i.test(text)) return false;
  const words = text.replace(/\bat (?:most|least)\b/gi, "");
  return /\b(?:ranks?|ranked|ranking|top|bottom|highest|lowest|most|least|fewest|largest|smallest|best|worst|busiest|ties|tied)\b/i.test(words);
}
export function rankTimeoutReply(record) {
  if (!record?.loaded || !record.revision || record.archived || record.historyLoading || record.operation) return null;
  const reply = record.messages.at(-1);
  if (!reply?.id || reply.conversationId !== record.id || reply.role !== "aqua" || reply.status !== "error"
    || reply.sequence !== record.messageCount || !reply.requestId || !reply.replyTo || reply.resultUnavailable
    || reply.response?.status !== "error" || reply.response.error?.code !== "model_timeout") return null;
  const input = record.messages.find(item => item.id === reply.replyTo && item.role === "user");
  if (!input || input.conversationId !== record.id || input.status !== "complete" || input.sequence >= reply.sequence || typeof input.content !== "string"
    || (record.draft !== "" && record.draft !== input.content)) return null;
  return isOrdinaryRanking(input.content) ? reply : null;
}
export function matchesRankRecovery(state, access, history, binding) {
  if (!access.canQuery || !access.canReadResults || access.suspended || !binding.ownerId || history.owner !== binding.ownerId
    || state.activeId !== binding.chatId || state.deletedChatIds?.includes(binding.chatId)) return false;
  const reply = rankTimeoutReply(state.records[binding.chatId]);
  return Boolean(reply && reply.id === binding.replyId && reply.requestId === binding.requestId);
}
export function isUnsentChatDraft(record, text) {
  return Boolean(record?.id?.startsWith("draft-") && record.draft === text && !record.operation && !record.revision
    && !record.messages.length && !record.messageCount && !record.historyLoading && !record.archived);
}
export function isEmptyChatDraft(record) {
  return isUnsentChatDraft(record, "");
}
// A draft belongs to its project and stays local until the normal Send action.
export function startProjectDraft(state, projectId, draft = "") {
  const records = Object.values(state.records);
  const empty = records.find(item => item.projectId === projectId && isEmptyChatDraft(item));
  if (!empty && records.length >= 100) return null;
  const item = { ...(empty || emptyConversation()), projectId, draft };
  return { ...state, records: { ...state.records, [item.id]: item }, activeId: item.id, notice: "" };
}
export function applyRankingPreview(state, access, history, binding, value) {
  const { ownerId, chatId, projectId, original } = binding;
  const record = state.records[chatId];
  if (!access.canQuery || !access.canReadResults || access.suspended || !ownerId || history.owner !== ownerId
    || state.activeId !== chatId || state.deletedChatIds?.includes(chatId) || !isUnsentChatDraft(record, original)
    || record.projectId !== projectId || typeof value !== "string" || !value || value.length > 2000) return state;
  if (original === "") return applyEmptyChatDraft(state, chatId, value);
  return isOrdinaryRanking(original) ? startProjectDraft(state, projectId, value) : state;
}
export function applyEmptyChatDraft(state, id, value) {
  const record = state.records[id];
  if (state.activeId !== id || !isEmptyChatDraft(record)) return state;
  return changeRecord(state, id, item => ({ ...item, draft: value }));
}
export function mergeMessages(previous, incoming) {
  const byId = new Map(previous.map((message) => [message.id, message]));
  incoming.forEach((message) => byId.set(message.id, message));
  return [...byId.values()].sort((left, right) => (left.sequence ?? Number.MAX_SAFE_INTEGER) - (right.sequence ?? Number.MAX_SAFE_INTEGER)).slice(-200);
}
export function maskSavedResults(messages, canReadResults) {
  return canReadResults ? messages : messages.map((message) => message.role !== "aqua" ? message : { ...message, content: "", resultUnavailable: true,
    response: { status: "error", sql: "", tables: [], visualizations: [], kpis: [], error: {
      code: "access_denied", message: "This saved result is unavailable with your current data access.", retryable: false } } });
}
export function finishHistory(state, id, page, older, canReadResults) {
  return changeRecord(state, id, (item) => ({ ...item, loaded: true, historyLoading: false,
    messages: maskSavedResults(older ? mergeMessages(page.items, item.messages) : page.items, canReadResults), olderCursor: page.cursor }));
}
export function openConversation(state, summary) {
  if (state.deletedChatIds?.includes(summary.id)) return state;
  const previous = state.records[summary.id];
  const records = { ...state.records, [summary.id]: { draft: "", messages: [], loaded: false, olderCursor: null, operation: null, ...previous, ...summary } };
  // Keep drafts, but retain bounded transcript caches. Server history remains
  // authoritative and can be fetched again without discarding unsent text.
  const loaded = Object.values(records).filter((item) => item.loaded && item.id !== summary.id && !item.operation).sort((a, b) => b.updatedAt - a.updatedAt);
  loaded.forEach((item) => { records[item.id] = { ...item, loaded: false, messages: [], olderCursor: null }; });
  return { ...state, records, activeId: summary.id, notice: "" };
}
export function finishSubmission(state, recordId, clientId, result, canReadResults = true) {
  const current = state.records[recordId];
  if (!current || current.operation?.clientId !== clientId) return state;
  if (state.deletedChatIds?.includes(result.chat.id)) return changeRecord(state, recordId, (item) => ({ ...item,
    title: "Draft from deleted chat", draft: item.draft || item.operation.prompt, messages: [], messageCount: 0,
    revision: null, projectId: null, loaded: true, olderCursor: null, operation: null }));
  // The server creates the chat before model work. A different visit to that
  // canonical ID may already hold newer text or another in-flight operation.
  const destination = result.chat.id !== recordId ? state.records[result.chat.id] : null;
  const summary = destination?.revision > result.chat.revision ? destination : result.chat;
  const pending = ["pending", "queued", "running", "cancelling"].includes(result.request.state);
  const lifecycle = Number.isSafeInteger(result.request.version);
  const messages = [...current.messages, ...(destination?.messages || [])].filter((message) => message.optimisticOperation !== clientId);
  const draft = destination?.draft || current.draft;
  const recover = !destination?.operation && !messages.some((message) => message.role === "aqua" && message.sequence > result.assistant.sequence);
  const record = { ...current, ...destination, ...summary, loaded: true, messages: maskSavedResults(mergeMessages(messages, [result.input, result.assistant]), canReadResults),
    draft: !draft && recover && result.assistant.response?.status === "error" ? current.operation.prompt : draft,
    operation: destination?.operation || (pending && !lifecycle ? { ...current.operation, busy: false, uncertain: true } : null) };
  if (state.activeId !== recordId && state.activeId !== record.id && !pending && !record.operation) { record.messages = []; record.loaded = false; }
  const records = { ...state.records }; delete records[recordId]; records[record.id] = record;
  const retainPending = pending && !lifecycle && destination?.operation;
  if (retainPending || destination?.draft && current.draft && destination.draft !== current.draft) records[recordId] = { ...current,
    title: retainPending ? "Pending saved request" : "Recovered unsent draft", draft: current.draft || current.operation.prompt,
    messages: [], messageCount: 0, revision: null, projectId: null, loaded: true, olderCursor: null,
    operation: retainPending ? { ...current.operation, busy: false, uncertain: true } : null };
  return { ...state, records, activeId: state.activeId === recordId ? record.id : state.activeId };
}
export function removeConversation(state, id) {
  const records = { ...state.records }; delete records[id];
  let activeId = state.activeId;
  if (activeId === id) { const draft = emptyConversation(); records[draft.id] = draft; activeId = draft.id; }
  // This exceeds the number of allowed deletes during the 120s response window.
  const deletedChatIds = [...new Set([...(state.deletedChatIds || []), id])].slice(-1000);
  return { ...state, records, activeId, deletedChatIds };
}
export function failSubmission(state, recordId, operation, uncertain) {
  return changeRecord(state, recordId, (item) => item.operation?.clientId !== operation.clientId ? item : ({ ...item,
    operation: uncertain ? { ...operation, busy: false, uncertain: true } : null,
    draft: item.draft || operation.prompt,
    messages: item.messages.filter((message) => message.optimisticOperation !== operation.clientId || uncertain && message.role === "user") }));
}
export function changeRecord(state, id, transform) {
  return state.records[id] ? { ...state, records: { ...state.records, [id]: transform(state.records[id]) } } : state;
}
