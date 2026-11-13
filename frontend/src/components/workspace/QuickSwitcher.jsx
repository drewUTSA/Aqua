import React, { useId, useRef, useState } from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";
import { quickSwitchItems } from "./quickSwitchPolicy.js";
import "../../styles/quick-switcher.css";

export default function QuickSwitcher({ chat, onClose, onSelect, onAction }) {
  const [query, setQuery] = useState(""), input = useRef(null), results = useRef(null), id = useId();
  const items = quickSwitchItems(chat, query);
  const choose = (item) => {
    onClose();
    if (item.kind === "chat") onSelect(item.item.id, item.item);
    else onAction(item.id);
  };
  const keyboard = (event) => {
    if (event.nativeEvent.isComposing || event.keyCode === 229) return;
    if (event.key === "Enter" && event.target === input.current && items.length) { event.preventDefault(); choose(items[0]); return; }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    // Home/End in the search field retain ordinary text editing behavior.
    if (event.target === input.current && ["Home", "End"].includes(event.key)) return;
    const buttons = [...results.current.querySelectorAll("button")];
    if (!buttons.length) return;
    event.preventDefault();
    const index = buttons.indexOf(document.activeElement);
    const next = event.key === "Home" ? 0 : event.key === "End" ? buttons.length - 1
      : event.key === "ArrowDown" ? (index + 1) % buttons.length : index <= 0 ? buttons.length - 1 : index - 1;
    buttons[next].focus();
  };
  return <PreferenceDialog title="Go to anything" className="quick-switcher" initialFocusRef={input} onClose={onClose}>
    <div onKeyDown={keyboard}>
      <label htmlFor={id}>Find an action, chat or draft</label>
      <input ref={input} id={id} type="search" value={query} maxLength={120} autoComplete="off" spellCheck={false}
        aria-describedby={`${id}-scope ${id}-count`} placeholder="Search your workspace…" onChange={(event) => setQuery(event.target.value)} />
      <p id={`${id}-scope`} className="quick-switcher__hint">{chat.durable ? "Searches loaded titles in this account. Choose “Search saved chats” to look beyond this page." : "Searches demo titles in this visit. Demo chats are not saved to an account."}</p>
      <p id={`${id}-count`} role="status" className="quick-switcher__hint">{items.length ? `${items.length} ${items.length === 1 ? "shortcut" : "shortcuts"} shown · ↑ ↓ to navigate` : "No loaded matches. Try fewer words or search saved chats."}</p>
      <div ref={results} className="quick-switcher__results" aria-label="Workspace shortcuts">
        {items.map((item) => <button key={item.id} type="button" onClick={() => choose(item)}
          aria-current={item.kind === "chat" && item.item.id === chat.activeConversationId ? "page" : undefined}>
          <span className="quick-switcher__symbol" aria-hidden="true">{item.kind === "chat" ? "↗" : "⌘"}</span>
          <span><strong>{item.label}</strong><small>{item.detail}</small></span>
          {item.kind === "chat" && item.item.id === chat.activeConversationId && <small>Current</small>}
        </button>)}
      </div>
      {!items.length && <button type="button" onClick={() => { onClose(); onAction("search"); }}>Search saved chats</button>}
    </div>
    <div className="quick-switcher__footer"><span>Esc to close · / to focus your question</span><button type="button" onClick={onClose}>Close</button></div>
  </PreferenceDialog>;
}
