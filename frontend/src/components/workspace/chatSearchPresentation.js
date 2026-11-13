// A failed or superseded read must never relabel old results as a new match.
export function chatSearchPresentation(chat, localSearch = "") {
  const filters = chat.filters || {}, page = chat.chats || {};
  const stale = chat.durable && page.criteria && ["search", "projectId", "archived"].some((key) => page.criteria[key] !== filters[key]);
  const loading = Boolean(chat.durable && !page.error && (page.loading || stale));
  const failed = Boolean(chat.durable && page.error);
  const items = loading || failed ? [] : (chat.conversations || []).filter((item) => chat.durable ? item.messageCount > 0 : item.messages?.length > 0);
  const matches = chat.durable ? items : items.filter((item) => item.title.toLowerCase().includes(localSearch.toLowerCase()));
  const status = failed ? "Chat search could not load. Try searching again."
    : loading ? "Loading matching chats…" : `${matches.length} ${matches.length === 1 ? "chat matches" : "chats match"} on this page.`;
  return { matches, loading, failed, status };
}
