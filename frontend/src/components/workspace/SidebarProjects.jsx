import React, { useId, useState } from "react";
import SidebarActionMenu from "./SidebarActionMenu.jsx";
import SidebarChatRow from "./SidebarChatRow.jsx";

export default function SidebarProjects({ chat, projectChats, onNewChat, onSelect, onEdit }) {
  const [visible, setVisible] = useState(true), heading = useId(), projects = chat.durable ? chat.projects : { items: [], loading: false };
  return <section className="refined-nav-section" aria-labelledby={heading}><div className="refined-section-heading">
    <h2 id={heading}><button type="button" aria-expanded={visible} onClick={() => setVisible((value) => !value)}>Projects<span aria-hidden="true">{visible ? "⌄" : "›"}</span></button></h2>
    <button type="button" className="refined-section-action" aria-label="New project" title="New project" disabled={!chat.durable || chat.busy}
      onClick={() => { setVisible(true); onEdit({ kind: "project", mode: "create" }); }}><span aria-hidden="true">+</span></button></div>
    {visible && <div className="refined-section-content">
      {!chat.durable && <p className="refined-sidebar-note">Projects are available with a signed-in account.</p>}
      {projects.items.map((project) => <div className="refined-project" key={project.id}>
        <div className="refined-project__row"><button type="button" className="refined-project-select" title={project.name}
          aria-expanded={projectChats.projectId === project.id} onClick={() => projectChats.toggle(project.id)}>
          <span className="refined-folder-icon" aria-hidden="true">▱</span><span>{project.name}</span><span className="refined-project-caret" aria-hidden="true">{projectChats.projectId === project.id ? "⌄" : "›"}</span></button>
          <SidebarActionMenu label={`Project actions: ${project.name}`} items={[
            { key: "new-chat", label: "New chat in project", action: () => onNewChat(project.id) },
            { key: "rename", label: "Rename project", disabled: chat.busy, action: () => onEdit({ kind: "project", mode: "rename", item: project }) },
            { key: "delete", label: "Delete project", danger: true, disabled: chat.busy, action: () => onEdit({ kind: "project", mode: "delete", item: project }) }
          ]} /></div>
        {projectChats.projectId === project.id && <div className="refined-project-chats" aria-label={`Chats in ${project.name}`} aria-busy={projectChats.loading}>
          {projectChats.loading ? <p className="refined-sidebar-note" role="status">Loading chats…</p> : projectChats.error ? <div><p role="alert" className="refined-sidebar-error">{projectChats.error}</p>
            <button type="button" onClick={projectChats.refresh}>Retry project chats</button></div>
            : <>{projectChats.items.map((item) => <SidebarChatRow key={item.id} item={item} chat={chat} onSelect={onSelect} onEdit={onEdit} onChanged={projectChats.refresh} />)}
              {!projectChats.items.length && <button type="button" className="refined-empty-action" onClick={() => onNewChat(project.id)}>Start a chat in this project</button>}
              {projectChats.cursor && <button type="button" className="refined-more" onClick={() => projectChats.load(project.id, projectChats.cursor)}>More project chats</button>}
              {projectChats.fromCursor && <button type="button" className="refined-more" onClick={() => projectChats.load(project.id)}>First project chats</button>}</>}
        </div>}
      </div>)}
      {projects.loading && <p className="refined-sidebar-note" role="status">Loading projects…</p>}
      {chat.durable && !projects.loading && !projects.items.length && <p className="refined-sidebar-note">No projects yet.</p>}
      {projects.cursor && <button type="button" className="refined-more" disabled={projects.loading} onClick={chat.moreProjects}>More projects</button>}
      {projects.fromCursor && <button type="button" className="refined-more" disabled={projects.loading} onClick={chat.firstProjects}>First projects</button>}
    </div>}
  </section>;
}
