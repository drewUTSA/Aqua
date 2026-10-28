import React, { useEffect, useId, useState } from "react";
import SidebarActionMenu from "./SidebarActionMenu.jsx";
import SidebarChatRow from "./SidebarChatRow.jsx";
import { SidebarRecoveryDialog, SidebarSearchDialog } from "./SidebarRecentsDialogs.jsx";
import { recentChats, recoverableChats } from "./sidebarState.js";

export default function SidebarRecents({ chat, preferences, recoveryOnly = false, onSelect, onEdit, onChanged }) {
  const [visible, setVisible] = useState(true), [dialog, setDialog] = useState(null), [showPage, setShowPage] = useState(false), [olderPage, setOlderPage] = useState(false), heading = useId();
  const items = recentChats(chat), recovery = recoverableChats(chat), loading = chat.durable && chat.chats.loading;
  const pageSize = preferences?.recents_count || 10;
  useEffect(() => { setShowPage(false); setOlderPage(false); }, [chat.filters?.search, chat.filters?.archived]);
  const menu = [{ key: "search", label: "Search chats", action: () => setDialog("search") }];
  if (chat.durable) menu.push(
    { key: "archive", label: chat.filters.archived ? "Recent chats" : "Archived chats", action: () => {
      setVisible(true); chat.filter({ search: "", archived: !chat.filters.archived, projectId: null });
    } },
    { key: "refresh", label: "Latest chats", disabled: loading, action: () => { setVisible(true); setOlderPage(false); void chat.refreshChats(); } }
  );
  if (recovery.length) menu.push({ key: "recovery", label: `Unsent drafts (${recovery.length})`, action: () => setDialog("recovery") });
  return <section className="refined-nav-section" aria-labelledby={heading}><div className="refined-section-heading">
    <h2 id={heading}><button type="button" aria-expanded={visible} onClick={() => setVisible((value) => !value)}>Recents<span aria-hidden="true">{visible ? "⌄" : "›"}</span></button></h2>
    <SidebarActionMenu label="Recents actions" items={menu} /></div>
    {visible && !recoveryOnly && <div className="refined-section-content">{chat.filters?.archived && <p className="refined-sidebar-note">Archived chats</p>}
      {chat.filters?.search && <button type="button" className="refined-filter" onClick={() => chat.filter({ search: "", projectId: null })}>Clear chat search</button>}
      {(showPage ? items : items.slice(0, pageSize)).map((item) => <SidebarChatRow key={item.id} item={item} chat={chat} onSelect={onSelect} onEdit={onEdit} onChanged={onChanged} />)}
      {loading && <p className="refined-sidebar-note" role="status">Loading chats…</p>}
      {!loading && !items.length && <p className="refined-sidebar-note">{chat.filters?.search ? "No matching chat titles." : chat.filters?.archived ? "No archived chats." : "No recent chats."}</p>}
      {!showPage && items.length > pageSize && <button type="button" className="refined-more" onClick={() => setShowPage(true)}>More chats</button>}
      {chat.durable && chat.chats.cursor && (showPage || items.length <= pageSize) && <button type="button" className="refined-more" disabled={loading}
        onClick={() => { setShowPage(true); setOlderPage(true); void chat.moreChats(); }}>Older chats</button>}
      {olderPage && <button type="button" className="refined-more" disabled={loading} onClick={() => { setOlderPage(false); void chat.refreshChats(); }}>First chats</button>}
    </div>}
    {dialog === "search" && <SidebarSearchDialog chat={chat} onSelect={onSelect} onClose={() => setDialog(null)} />}
    {dialog === "recovery" && <SidebarRecoveryDialog items={recovery} onSelect={onSelect} onClose={() => setDialog(null)} />}
  </section>;
}
