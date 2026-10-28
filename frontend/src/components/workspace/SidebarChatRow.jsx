import React, { useRef, useState } from "react";
import SidebarActionMenu from "./SidebarActionMenu.jsx";

export default function SidebarChatRow({ item, chat, onSelect, onEdit, onChanged }) {
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const lock = useRef(false);
  const archive = async () => {
    if (lock.current) return; lock.current = true; setBusy(true); setError("");
    try {
      if (await chat.mutateChat(item, { archived: !item.archived })) onChanged?.(item.id);
      else setError("The archive change was not confirmed. Refresh the list and retry.");
    } catch { setError("The archive change could not be confirmed. Refresh the list and retry."); }
    finally { lock.current = false; setBusy(false); }
  };
  const actions = [
    { key: "rename", label: "Rename chat", action: () => onEdit({ kind: "chat", mode: "rename", item }), disabled: busy },
    { key: "move", label: "Move to project", action: () => onEdit({ kind: "chat", mode: "move", item }), disabled: busy },
    { key: "archive", label: item.archived ? "Unarchive chat" : "Archive chat", action: archive, disabled: busy },
    { key: "delete", label: "Delete chat", danger: true, action: () => onEdit({ kind: "chat", mode: "delete", item }), disabled: busy }
  ];
  return <div className="refined-chat-row" data-active={item.id === chat.activeConversationId || undefined}>
    <div className="refined-chat-row__main"><button type="button" className="refined-chat-select" disabled={busy}
      aria-current={item.id === chat.activeConversationId ? "page" : undefined} onClick={() => onSelect(item.id, item)} title={item.title}>
      <span>{item.title}</span></button>{chat.durable && <SidebarActionMenu label={`Chat actions: ${item.title}`} items={actions} />}</div>
    {error && <p className="refined-sidebar-error" role="alert">{error}</p>}
  </div>;
}
