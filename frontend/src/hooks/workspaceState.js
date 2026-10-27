import { operationId } from "../services/workspaceClient.js";

export function emptyConversation() {
  return { id: `draft-${operationId()}`, title: "New chat", draft: "", messages: [], messageCount: 0, updatedAt: Date.now(),
    projectId: null, archived: false, revision: null, loaded: true, olderCursor: null, operation: null };
}
export function initialWorkspace() {
  const conversation = emptyConversation();
  return { activeId: conversation.id, records: { [conversation.id]: conversation }, deletedChatIds: [], notice: "", loading: false };
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
