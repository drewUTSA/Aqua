import { recentChats, recoverableChats } from "./sidebarState.js";

const normalize = (value) => String(value || "").normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase("en");

// Index only titles already held by this mounted owner. Draft/message bodies,
// server-wide search, private persistence and automatic submissions stay out.
export function quickSwitchItems(chat, query = "") {
  const actions = [
    { id: "new", label: "New chat", detail: "Start a conversation", kind: "action" },
    { id: "search", label: "Search saved chats", detail: chat.durable ? "Search titles on the server" : "Search titles in this visit", kind: "action" },
    { id: "prompts", label: "Saved prompts", detail: "Choose a prompt to review", kind: "action" },
    { id: "settings", label: "Settings", detail: "Appearance, account and preferences", kind: "action" },
  ];
  const seen = new Set(), records = [];
  for (const [items, recovery] of [[recoverableChats(chat), true], [recentChats(chat), false]]) {
    for (const item of items) {
      if (seen.has(item.id)) continue;
      seen.add(item.id);
      const detail = recovery ? "Draft or pending request · this visit" : !chat.durable ? "Chat · this visit" : item.archived ? "Archived chat" : "Saved chat";
      records.push({ id: `chat:${item.id}`, label: item.title || "New chat", detail, kind: "chat", item });
    }
  }
  const terms = normalize(query.slice(0, 120)).trim().split(/\s+/).filter(Boolean);
  return [...actions, ...records].filter((item) => {
    const text = normalize(`${item.label} ${item.detail}`);
    return terms.every((term) => text.includes(term));
  }).slice(0, 20);
}

export function workspaceShortcut(event, { hidden = false, modalOpen = false } = {}) {
  if (hidden || modalOpen || event.defaultPrevented || event.repeat || event.isComposing || event.keyCode === 229 || event.altKey) return null;
  if ((event.ctrlKey || event.metaKey) && !event.shiftKey && event.key.toLowerCase() === "k") return "switch";
  const editable = event.target?.closest?.("input,textarea,select,[contenteditable]:not([contenteditable=false]),[role=textbox]");
  if (event.key === "/" && !event.ctrlKey && !event.metaKey && !event.shiftKey && !editable) return "composer";
  return null;
}
