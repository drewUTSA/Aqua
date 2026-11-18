import { resultReference } from "./reference.js";
export { isSavedResultCandidate } from "./reference.js";
const plain = value => value && typeof value === "object" && !Array.isArray(value);
export function resultBinding(chat, ownerId, messageId, allowed) {
  const reference = resultReference(chat, ownerId, messageId, allowed);
  if (!reference) return null;
  const message = chat.messages?.find(item => item.id === messageId), response = message?.response;
  const table = response.tables[0];
  if (!plain(table) || table.id !== "result" || !Array.isArray(table.columns) || !table.columns.length || table.columns.length > 64
    || !Array.isArray(table.rows) || table.rows.length > 1000 || !table.rows.every(plain)
    || !table.columns.every(column => plain(column) && typeof column.key === "string" && column.key.length > 0 && [...column.key].length <= 256
      && new TextEncoder().encode(column.key).length <= 1024 && !/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\uD800-\uDFFF]/u.test(column.key))
    || new Set(table.columns.map(column => column.key)).size !== table.columns.length) return null;
  const original = chat.messages.find(item => item.id === message.replyTo && item.role === "user" && item.requestId === message.requestId)?.content;
  const question = typeof original === "string" && [...original].length <= 2000 && new TextEncoder().encode(original).length <= 8000
    && !/[\u0000-\u0008\u000b-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069\uD800-\uDFFF]/u.test(original) ? original : null;
  return { ...reference, table, question,
    metadata: response.resultMetadata };
}

export function sameResultBinding(left, right) {
  return Boolean(left && right && left.token === right.token && left.ownerId === right.ownerId && left.requestId === right.requestId);
}
