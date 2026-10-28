import React, { useRef, useState } from "react";
import WorkspaceEditor from "./WorkspaceEditor.jsx";

export default function WorkspaceLibrary({ chat, onPrompt, section }) {
  const [editor, setEditor] = useState(null);
  const current = useRef(chat); current.current = chat;
  return <>
    {(!section || section === "prompts") && <section aria-label="Private saved prompts"><h2>Saved prompts</h2><p className="sidebar-note">Private to your account. Applying a prompt never submits it.</p>
      <button type="button" onClick={() => setEditor({ kind: "prompt" })}>Save a prompt</button>
      {chat.prompts.items.map((item) => <div className="workspace-library-row" key={item.id}><button type="button" disabled={chat.busy}
        onClick={async () => { const target = chat.activeConversationId, draft = chat.draft;
          if (await chat.usePrompt(item) && current.current.activeConversationId === target && current.current.draft === draft) onPrompt(item.prompt); }}><span>{item.pinned ? "★ " : ""}{item.label}</span></button>
        <button type="button" aria-label={`Edit saved prompt ${item.label}`} onClick={() => setEditor({ kind: "prompt", item })}>Edit</button></div>)}
      {chat.prompts.loading && <p className="sidebar-note" role="status">Loading saved prompts…</p>}
      {!chat.prompts.loading && !chat.prompts.items.length && <p className="sidebar-note">No saved prompts yet.</p>}
      {chat.prompts.cursor && <button type="button" disabled={chat.prompts.loading} onClick={chat.morePrompts}>More saved prompts</button>}
      {chat.prompts.fromCursor && <button type="button" disabled={chat.prompts.loading} onClick={chat.firstPrompts}>First saved prompts</button>}
    </section>}
    {(!section || section === "projects") && <section aria-label="Private projects"><h2>Projects</h2><button type="button" onClick={() => setEditor({ kind: "project" })}>New project</button>
      <button type="button" aria-pressed={!chat.filters.projectId} onClick={() => chat.filter({ projectId: null })}>All chats</button>
      {chat.projects.items.map((item) => <div className="workspace-library-row" key={item.id}><button type="button" aria-pressed={chat.filters.projectId === item.id}
        onClick={() => chat.filter({ projectId: item.id })}>{item.name}</button><button type="button" aria-label={`Edit project ${item.name}`} onClick={() => setEditor({ kind: "project", item })}>Edit</button></div>)}
      {chat.projects.loading && <p className="sidebar-note" role="status">Loading projects…</p>}
      {!chat.projects.loading && !chat.projects.items.length && <p className="sidebar-note">No projects yet.</p>}
      {chat.projects.cursor && <button type="button" disabled={chat.projects.loading} onClick={chat.moreProjects}>More projects</button>}
      {chat.projects.fromCursor && <button type="button" disabled={chat.projects.loading} onClick={chat.firstProjects}>First projects</button>}
    </section>}
    {editor && <WorkspaceEditor key={`${editor.kind}:${editor.item?.id || "new"}`} {...editor} onClose={() => setEditor(null)}
      onSave={(values, requestId) => editor.kind === "prompt" ? chat.savePrompt(editor.item, values, requestId) : chat.saveProject(editor.item, values.name, requestId)}
      onDelete={() => editor.kind === "prompt" ? chat.deletePrompt(editor.item) : chat.deleteProject(editor.item)} />}
  </>;
}
