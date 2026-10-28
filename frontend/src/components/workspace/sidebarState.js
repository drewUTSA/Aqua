// Keep visit-local recovery discoverable without a standing draft section.
// Values remain within the mounted account; no private text is persisted here.
export function recoverableChats(chat) {
  const source = chat.recoverableDrafts || chat.drafts || (chat.conversations || []).filter((item) => item.draft?.trim() || item.operation || item.request);
  const unique = new Map(source.map((item) => [item.id, item]));
  if ((chat.pending || chat.uncertain) && chat.active) unique.set(chat.active.id, chat.active);
  return [...unique.values()].slice(0, 100);
}
export function recentChats(chat) {
  return (chat.conversations || []).slice(0, 100).filter((item) => chat.durable ? item.messageCount > 0 : item.messages?.length > 0);
}
