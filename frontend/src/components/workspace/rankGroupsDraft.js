import { isOrdinaryRanking } from "../../hooks/workspaceState.js";

export const initialRankFields = {
  source: "", group: "", measure: "count", field: "", direction: "top", number: "3", ties: "peers",
};

export function canStartGroupRank({ auth, chat, visible, active }) {
  return Boolean(visible && !active && !auth.demoMode && auth.canQuery && auth.session?.can_query === true
    && chat.durable && chat.activeConversationId?.startsWith("draft-") && (chat.draft === "" || isOrdinaryRanking(chat.draft))
    && !chat.active?.revision && !chat.active?.operation && !chat.active?.historyLoading && !chat.active?.archived && !chat.pending && !chat.uncertain);
}

// Each input names one thing. Keep sentence punctuation and instructions out of the labels.
// The server resolves the final request against the employee's granted analytical scope.
export function rankLabel(value) {
  if (typeof value !== "string" || value.length > 64) return "";
  const clean = value.trim();
  return /^[A-Za-z][A-Za-z0-9]*(?:[ _-][A-Za-z0-9]+)*$/.test(clean) ? clean : "";
}

export function validRankNumber(value) {
  return /^[1-9][0-9]{0,3}$/.test(String(value)) && Number(value) <= 1000;
}

export function rankGroupsDraft(fields) {
  const source = rankLabel(fields.source), group = rankLabel(fields.group);
  const field = rankLabel(fields.field), number = String(fields.number);
  if (!source || !group || !validRankNumber(number)) return "";
  if (!["top", "bottom"].includes(fields.direction) || !["count", "total"].includes(fields.measure)) return "";
  if (fields.measure === "total" && !field) return "";
  const metric = fields.measure === "count" ? "row count" : `total ${field}`;
  const start = `Rank groups: From ${source}, `;
  if (fields.ties === "levels") {
    const order = fields.direction === "top" ? "highest" : "lowest";
    return `${start}which ${group} have one of the ${order} ${number} distinct ${metric} values?`;
  }
  const rank = `the ${fields.direction} ${number} ${group} by ${metric}`;
  if (fields.ties === "fixed") return `${start}show exactly ${rank}.`;
  if (fields.ties === "peers") return `${start}show ${rank}, including ties.`;
  return "";
}
