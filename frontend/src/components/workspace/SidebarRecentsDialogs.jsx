import React, { useId, useState } from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";

export function SidebarSearchDialog({ chat, onSelect, onClose }) {
  const inputId = useId(), [search, setSearch] = useState(chat.filters?.search || ""), [localSearch, setLocalSearch] = useState("");
  const items = (chat.conversations || []).filter((item) => chat.durable ? item.messageCount > 0 : item.messages?.length > 0);
  const matches = chat.durable ? items : items.filter((item) => item.title.toLowerCase().includes(localSearch.toLowerCase()));
  const loading = chat.durable && chat.chats.loading;
  return <PreferenceDialog title="Search chats" className="refined-search-dialog" onClose={onClose}>
    <form className="sidebar-search" onSubmit={(event) => { event.preventDefault();
      if (chat.durable) chat.filter({ search: search.trim(), projectId: null, archived: false }); else setLocalSearch(search.trim());
    }}><label htmlFor={inputId}>Search chat titles</label><input id={inputId} type="search" autoFocus value={search} maxLength={chat.durable ? 80 : 120}
      autoComplete="off" onChange={(event) => setSearch(event.target.value)} />
      <div className="settings-dialog-actions"><button type="button" onClick={onClose}>Close search</button>
        <button type="submit" disabled={loading}>Search</button></div>
      <p className="sidebar-search__status" role="status">{loading ? "Loading matching chats…" : `${matches.length} ${matches.length === 1 ? "chat matches" : "chats match"} on this page.`}</p>
      <p className="refined-sidebar-note">{chat.durable ? "Matches titles starting with your text. Message contents are not searched." : "Searches titles in this visit only."}</p>
      {(search || chat.filters?.search) && <button type="button" onClick={() => { setSearch(""); setLocalSearch("");
        if (chat.durable) chat.filter({ search: "", projectId: null, archived: false }); }}>Clear chat search</button>}
    </form>
    <div className="refined-search-results">{!loading && matches.map((item) => <button type="button" key={item.id}
      aria-current={item.id === chat.activeConversationId ? "page" : undefined} onClick={() => { onClose(); onSelect(item.id, item); }}>{item.title}</button>)}</div>
    {chat.durable && chat.chats.cursor && <button type="button" disabled={loading} onClick={chat.moreChats}>More matching chats</button>}
  </PreferenceDialog>;
}
export function SidebarRecoveryDialog({ items, onSelect, onClose }) {
  return <PreferenceDialog title="Unsent drafts" className="refined-recovery-dialog" onClose={onClose}>
    <p>Unsent text and pending requests remain in this visit. Selecting one never submits or retries it.</p>
    <div className="refined-search-results">{items.map((item) => <button type="button" key={item.id} onClick={() => { onClose(); onSelect(item.id, item); }}>
      <span>Draft · {item.title || "New chat"}</span>{(item.operation || item.request) && <small>{item.operation?.uncertain ? "Confirmation needed" : "Request pending"}</small>}
    </button>)}</div>
    {!items.length && <p>No unsent drafts remain.</p>}<button type="button" autoFocus onClick={onClose}>Close drafts</button>
  </PreferenceDialog>;
}
