import { validId } from "../../services/workspaceContract.js";

// Weak identities retain neither result values nor a second result cache.
const identities = new WeakMap(); let nextIdentity = 0;
export function isSavedResultCandidate(message) {
  return Boolean(message && message.role === "aqua" && message.status === "complete" && message.historical === true && message.resultUnavailable === false
    && validId(message.id) && validId(message.requestId) && validId(message.conversationId) && message.response?.status === "success"
    && Array.isArray(message.response.tables) && message.response.tables.length === 1 && message.response.tables[0]?.id === "result"
    && Array.isArray(message.response.tables[0].columns) && message.response.tables[0].columns.length > 0 && message.response.tables[0].columns.length <= 64
    && Array.isArray(message.response.tables[0].rows) && message.response.tables[0].rows.length <= 1000);
}
export function resultReference(chat, ownerId, messageId, allowed) {
  if (!allowed || !chat?.durable || !validId(ownerId) || !validId(chat.activeConversationId) || chat.active?.historyLoading) return null;
  const message = chat.messages?.find(item => item.id === messageId), analysis = chat.active?.analyses?.[message?.requestId];
  if (!isSavedResultCandidate(message) || message.conversationId !== chat.activeConversationId || analysis && analysis.state !== "complete") return null;
  const jobVersion = Number.isSafeInteger(analysis?.version) && analysis.version >= 1 ? analysis.version : null;
  if (!identities.has(message.response)) identities.set(message.response, ++nextIdentity);
  return { ownerId, chatId: message.conversationId, messageId: message.id, requestId: message.requestId, jobVersion,
    token: JSON.stringify([ownerId, message.conversationId, message.id, message.requestId, message.sequence, jobVersion, identities.get(message.response)]) };
}
