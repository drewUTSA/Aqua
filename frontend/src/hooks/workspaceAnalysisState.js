import { terminalAnalysis } from "../services/workspaceContract.js";
import { changeRecord, mergeMessages, maskSavedResults } from "./workspaceState.js";

export function acceptAnalysis(state, snapshot, canReadResults) {
  const { chat, request, input, assistant } = snapshot, record = state.records[chat.id];
  if (!record || state.deletedChatIds?.includes(chat.id)) return state;
  const previous = record.analyses?.[request.id];
  if (previous && (previous.version > request.version || previous.version === request.version && previous.sequence > request.sequence
    || terminalAnalysis(previous.state) && previous.state !== request.state)) return state;
  const summary = record.revision > chat.revision ? record : chat;
  const latestReply = Math.max(0, ...record.messages.filter((message) => message.role === "aqua").map((message) => message.sequence || 0));
  const recover = terminalAnalysis(request.state) && request.state !== "complete" && !record.operation && assistant.sequence >= latestReply;
  const analyses = Object.fromEntries(Object.values({ ...record.analyses, [request.id]: { ...request, replySequence: assistant.sequence } })
    .sort((left, right) => Number(terminalAnalysis(left.state)) - Number(terminalAnalysis(right.state)) || right.replySequence - left.replySequence).slice(0, 100).map((item) => [item.id, item]));
  const evict = state.activeId !== chat.id && terminalAnalysis(request.state) && !record.operation;
  return changeRecord(state, chat.id, (item) => ({ ...item, ...summary,
    analyses,
    messages: evict ? [] : maskSavedResults(mergeMessages(item.messages, [input, assistant]), canReadResults),
    draft: item.draft || (recover ? input.content : ""), loaded: !evict }));
}

export function progressAnalysis(state, event) {
  if (terminalAnalysis(event.state)) return state;
  const record = Object.values(state.records).find((item) => item.analyses?.[event.requestId]);
  if (!record || state.deletedChatIds?.includes(record.id)) return state;
  const previous = record.analyses[event.requestId];
  if (terminalAnalysis(previous.state) || previous.version > event.version || previous.version === event.version && previous.sequence >= event.sequence) return state;
  return changeRecord(state, record.id, (item) => ({ ...item, analyses: { ...item.analyses, [event.requestId]: {
    ...previous, version: event.version, sequence: event.sequence, state: event.state, stage: event.stage } } }));
}

export function activeAnalysis(record) {
  const known = Object.values(record.analyses || {}).sort((left, right) => (right.replySequence || 0) - (left.replySequence || 0));
  const pending = record.messages.filter((message) => message.role === "aqua" && message.status === "pending")
    .find((message) => !record.analyses?.[message.requestId]);
  return known.find((request) => !terminalAnalysis(request.state)) || (pending ? { id: pending.requestId, state: "pending", stage: "checking", cancellable: false } : known[0] || null);
}

export function analysisRequests(state) {
  const unique = new Map();
  for (const record of Object.values(state.records)) {
    if (state.deletedChatIds?.includes(record.id)) continue;
    for (const request of Object.values(record.analyses || {})) if (!terminalAnalysis(request.state)) unique.set(request.id, record.id);
    for (const message of record.messages) if (message.role === "aqua" && message.status === "pending"
      && !terminalAnalysis(record.analyses?.[message.requestId]?.state)) unique.set(message.requestId, record.id);
  }
  return [...unique].map(([id, chatId]) => ({ id, chatId })).sort((left, right) => Number(right.chatId === state.activeId) - Number(left.chatId === state.activeId)).slice(0, 4);
}
