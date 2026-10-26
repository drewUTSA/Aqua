import React, { useEffect, useId, useState } from "react";
import AccountMenu from "./AccountMenu.jsx";
import mark from "../../assets/opal/workspace/imgAquaConceptMark.svg";
import chatIcon from "../../assets/opal/workspace/imgIconChat.svg";
import plus from "../../assets/opal/workspace/imgIconPlus.svg";
import collapse from "../../assets/opal/workspace/imgIconCollapse.svg";
import ControlIcon from "./ControlIcon.jsx";
import WorkspaceLibrary from "./WorkspaceLibrary.jsx";
import WorkspaceEditor from "./WorkspaceEditor.jsx";
import "../../styles/sidebar-search.css";
export default function OpalSidebar({ chat, auth, onNewChat, onSelect, onPrompt, onNavigate, onClose }) {
  const searchId = useId();
  const [search, setSearch] = useState("");
  const [editing, setEditing] = useState(null);
  useEffect(() => { if (chat.durable) setSearch(chat.filters.search); }, [chat.filters?.search, chat.durable]);
  // Visit-local titles are already scoped to the mounted account. Literal
  // matching never submits a query, searches message bodies, or persists text.
  const needle = search.trim().toLowerCase();
  const recent = chat.conversations.slice(0, 100).filter((item) => chat.durable ? item.messageCount > 0 : item.messages.length > 0);
  const matches = chat.durable ? recent : needle ? recent.filter((item) => item.title.slice(0, 512).toLowerCase().includes(needle)) : recent;
  return <aside className="opal-sidebar" aria-label="Workspace navigation">
    <div className="opal-brand"><img src={mark} alt="" /><span>AQUA</span><button type="button" className="icon-button" onClick={onClose} aria-label="Close navigation"><ControlIcon asset={collapse} /></button></div>
    <button type="button" className="new-chat" onClick={onNewChat}><img src={plus} alt="" />New chat</button>
    <div className="opal-sidebar__scroll">
      <section><h2>{chat.durable ? "Starter questions" : "Frequent questions"}</h2>{chat.faqs.map((faq) => <button type="button" key={faq.id} disabled={!auth.canQuery} onClick={() => onPrompt(faq.prompt)}><img src={chatIcon} alt="" /><span>{faq.title}</span></button>)}</section>
      {chat.durable && chat.drafts.length > 0 && <section aria-label="Unsent drafts"><h2>Drafts in this visit</h2>
        {chat.drafts.map((item) => <button type="button" key={item.id} aria-pressed={item.id === chat.activeConversationId} onClick={() => onSelect(item.id)}>Draft · {item.title}</button>)}
        <p className="sidebar-note">Unsent text is kept in this page only.</p></section>}
      {chat.durable && <WorkspaceLibrary chat={chat} onPrompt={onPrompt} />}
      <section><h2>{chat.durable && chat.filters.archived ? "Archived chats" : "Recent chats"}{!chat.durable && <span className="sr-only">in this visit</span>}</h2>
        <p className="sidebar-note">{chat.durable ? "Submitted conversations are saved to your account." : "Stored for this visit only."}</p>
        <form className="sidebar-search" onSubmit={(event) => { event.preventDefault(); if (chat.durable) chat.filter({ search: search.trim() }); }}>
          <label htmlFor={searchId}>{chat.durable ? "Search chat titles" : "Search chats in this visit"}</label>
          <input id={searchId} type="search" value={search} maxLength={chat.durable ? 80 : 120} autoComplete="off" spellCheck="false"
            placeholder="Search chat titles" onChange={(event) => setSearch(event.target.value.slice(0, chat.durable ? 80 : 120))} />
          {chat.durable && <button type="submit" disabled={chat.chats.loading}>Search titles</button>}
          {search && <button type="button" className="sidebar-search__clear" onClick={() => { setSearch(""); if (chat.durable) chat.filter({ search: "" }); }}>Clear chat search</button>}
          <p className="sidebar-search__status" role="status" aria-live="polite">{chat.durable ? chat.chats.loading ? "Loading chat titles…" : `${matches.length} ${matches.length === 1 ? "chat matches" : "chats match"} on this page.`
            : needle ? `${matches.length} ${matches.length === 1 ? "chat matches" : "chats match"} this search.` : "Searches titles on this page only."}</p>
          {chat.durable && <p className="sidebar-note">Matches titles starting with your text; message contents are not searched.</p>}
        </form>
        {chat.durable && <div className="workspace-library-row"><button type="button" onClick={() => chat.filter({ archived: !chat.filters.archived })}>{chat.filters.archived ? "Show active chats" : "Show archived chats"}</button>
          <button type="button" disabled={chat.chats.loading} onClick={() => chat.refreshChats()}>Latest chats</button></div>}
        {matches.map((conversation) => <div className="workspace-library-row" key={conversation.id}><button type="button"
          aria-current={conversation.id === chat.activeConversationId ? "page" : undefined} onClick={() => onSelect(conversation.id)}><img src={chatIcon} alt="" /><span>{conversation.title}</span></button>
          {chat.durable && <button type="button" aria-label={`Edit chat ${conversation.title}`} onClick={() => setEditing(conversation)}>Edit</button>}</div>)}
        {!recent.length && <p className="sidebar-note">Your conversations will appear here.</p>}
        {recent.length > 0 && !matches.length && <p className="sidebar-note">No chats match this search.</p>}
        {chat.durable && chat.chats.cursor && <button type="button" disabled={chat.chats.loading} onClick={chat.moreChats}>More chats</button>}
      </section>
    </div>
    {editing && <WorkspaceEditor kind="chat" item={editing} projects={chat.projects.items} onClose={() => setEditing(null)}
      onSave={(values) => chat.mutateChat(editing, values)} onDelete={() => chat.mutateChat(editing, {}, true)} />}
    <div className="opal-account"><span className="account-initial" aria-hidden="true">{(auth.user?.name || "A").slice(0, 1)}</span>
      <div><span>{auth.user?.name || "AQUA user"}</span><small>{auth.demoMode ? "Fictional demo" : "Personal workspace"}</small></div>
      <AccountMenu auth={auth} onNavigate={onNavigate} placement="above" /></div>
  </aside>;
}
