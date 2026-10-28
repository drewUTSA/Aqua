import React, { useState } from "react";
import AccountMenu from "./AccountMenu.jsx";
import plus from "../../assets/opal/workspace/imgIconPlus.svg";
import collapse from "../../assets/opal/workspace/imgIconCollapse.svg";
import ControlIcon from "./ControlIcon.jsx";
import SidebarProjects from "./SidebarProjects.jsx";
import SidebarRecents from "./SidebarRecents.jsx";
import SidebarRecordDialog from "./SidebarRecordDialog.jsx";
import { useProjectChats } from "./useProjectChats.js";
import { recoverableChats } from "./sidebarState.js";
import "../../styles/sidebar-refined.css";

export default function OpalSidebar({ chat, auth, preferences, showNewChat = false, onNewChat, onSelect, onNavigate, onClose }) {
  const [editing, setEditing] = useState(null), projectChats = useProjectChats(auth);
  const sections = (preferences?.sidebar_sections || ["projects", "recents"]).filter((section) => ["projects", "recents"].includes(section));
  const recoveryOnly = !sections.includes("recents") && recoverableChats(chat).length > 0;
  if (recoveryOnly) sections.push("recents");
  const applied = (action) => {
    if (action.kind === "project" && action.mode === "delete" && projectChats.projectId === action.item.id) projectChats.close();
    else projectChats.refresh();
  };
  return <aside className="opal-sidebar refined-sidebar" aria-label="Workspace navigation">
    <div className="refined-sidebar__top"><button type="button" className="icon-button" onClick={onClose} aria-label="Close navigation"><ControlIcon asset={collapse} /></button></div>
    {showNewChat && <button type="button" className="new-chat refined-new-chat" onClick={() => onNewChat()}><ControlIcon asset={plus} />New chat</button>}
    <div className="opal-sidebar__scroll refined-sidebar__scroll">
      {sections.map((section) => section === "projects"
        ? <SidebarProjects key={section} chat={chat} projectChats={projectChats} onNewChat={onNewChat} onSelect={onSelect} onEdit={setEditing} />
        : <SidebarRecents key={section} chat={chat} preferences={preferences} recoveryOnly={recoveryOnly} onSelect={onSelect} onEdit={setEditing} onChanged={projectChats.refresh} />)}
    </div>
    {editing && <SidebarRecordDialog key={`${editing.kind}:${editing.mode}:${editing.item?.id || "new"}`} action={editing} chat={chat}
      onClose={() => setEditing(null)} onApplied={applied} />}
    <div className="opal-account refined-sidebar__account"><span className="refined-account-avatar" aria-hidden="true">{Array.from(auth.user?.name || "A")[0]}</span>
      <span className="refined-account-name" title={auth.user?.email || ""}>{auth.user?.name || "Your account"}</span>
      <AccountMenu auth={auth} onNavigate={onNavigate} placement="above" /></div>
  </aside>;
}
