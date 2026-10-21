import React, { useId, useState } from "react";
import AccountMenu from "./AccountMenu.jsx";
import mark from "../../assets/opal/workspace/imgAquaConceptMark.svg";
import chatIcon from "../../assets/opal/workspace/imgIconChat.svg";
import plus from "../../assets/opal/workspace/imgIconPlus.svg";
import collapse from "../../assets/opal/workspace/imgIconCollapse.svg";
import ControlIcon from "./ControlIcon.jsx";
import "../../styles/sidebar-search.css";
export default function OpalSidebar({ chat, auth, onNewChat, onSelect, onPrompt, onNavigate, onClose }) {
  const searchId = useId();
  const [search, setSearch] = useState("");
  // Visit-local titles are already scoped to the mounted account. Literal
  // matching never submits a query, searches message bodies, or persists text.
  const needle = search.trim().toLowerCase();
  const recent = chat.conversations.slice(0, 100).filter((item) => item.messages.length > 0);
  const matches = needle ? recent.filter((item) => item.title.slice(0, 512).toLowerCase().includes(needle)) : recent;
  return <aside className="opal-sidebar" aria-label="Workspace navigation">
    <div className="opal-brand"><img src={mark} alt="" /><span>AQUA</span><button type="button" className="icon-button" onClick={onClose} aria-label="Close navigation"><ControlIcon asset={collapse} /></button></div>
    <button type="button" className="new-chat" onClick={onNewChat}><img src={plus} alt="" />New chat</button>
    <div className="opal-sidebar__scroll">
      <section><h2>Frequent questions</h2>{chat.faqs.map((faq) => <button type="button" key={faq.id} disabled={!auth.canQuery} onClick={() => onPrompt(faq.prompt)}><img src={chatIcon} alt="" /><span>{faq.title}</span></button>)}</section>
      <section><h2>Recent chats <span className="sr-only">in this visit</span></h2><p className="sidebar-note">Stored for this visit only.</p>
        <div className="sidebar-search">
          <label htmlFor={searchId}>Search chats in this visit</label>
          <input id={searchId} type="search" value={search} maxLength={120} autoComplete="off" spellCheck="false"
            placeholder="Search chat titles" onChange={(event) => setSearch(event.target.value.slice(0, 120))} />
          {search && <button type="button" className="sidebar-search__clear" onClick={() => setSearch("")}>Clear chat search</button>}
          <p className="sidebar-search__status" role="status" aria-live="polite">{needle ? `${matches.length} ${matches.length === 1 ? "chat matches" : "chats match"} this search.` : "Searches titles on this page only."}</p>
        </div>
        {matches.map((conversation) => <button type="button" key={conversation.id}
          aria-current={conversation.id === chat.activeConversationId ? "page" : undefined} onClick={() => onSelect(conversation.id)}><img src={chatIcon} alt="" /><span>{conversation.title}</span></button>)}
        {!recent.length && <p className="sidebar-note">Your conversations will appear here.</p>}
        {recent.length > 0 && !matches.length && <p className="sidebar-note">No chats match this search.</p>}
      </section>
    </div>
    <div className="opal-account"><span className="account-initial" aria-hidden="true">{(auth.user?.name || "A").slice(0, 1)}</span>
      <div><span>{auth.user?.name || "AQUA user"}</span><small>{auth.demoMode ? "Fictional demo" : "Personal workspace"}</small></div>
      <AccountMenu auth={auth} onNavigate={onNavigate} placement="above" /></div>
  </aside>;
}
