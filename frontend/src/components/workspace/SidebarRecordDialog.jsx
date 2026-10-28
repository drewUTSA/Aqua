import React, { useId, useRef, useState } from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";
import { operationId } from "../../services/workspaceClient.js";

export default function SidebarRecordDialog({ action, chat, onClose, onApplied }) {
  const { kind, mode, item } = action, fieldId = useId();
  const [name, setName] = useState(item?.title || item?.name || ""), [projectId, setProjectId] = useState(item?.projectId || "");
  const [busy, setBusy] = useState(false), [error, setError] = useState("");
  const lock = useRef(false), requestId = useRef(null);
  const noun = kind === "project" ? "project" : "chat", deleting = mode === "delete", moving = mode === "move";
  const title = deleting ? `Delete ${noun}?` : moving ? "Move chat to project" : mode === "create" ? "New project" : `Rename ${noun}`;
  const submit = async (event) => {
    event?.preventDefault(); if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    if (!requestId.current) requestId.current = operationId();
    try {
      const values = moving ? { project_id: projectId || null } : kind === "chat" ? { title: name.trim() } : { name: name.trim() };
      const okay = kind === "project" ? deleting ? await chat.deleteProject(item) : await chat.saveProject(item, name.trim(), requestId.current)
        : await chat.mutateChat(item, deleting ? {} : values, deleting);
      if (okay) { onApplied?.({ ...action, values }); onClose(); }
      else setError("The change was not confirmed. Your edits are retained. Refresh the list before retrying if this item changed elsewhere.");
    } catch { setError("The change could not be confirmed. Your edits are retained; refresh the list and try again."); }
    finally { lock.current = false; setBusy(false); }
  };
  return <PreferenceDialog title={title} className="sidebar-record-dialog workspace-editor" busy={busy} onClose={onClose}>
    {deleting ? <><p>{kind === "project" ? "This removes the project. Its chats stay in your account without a project."
      : "This permanently deletes this chat and its saved messages and results."}</p><p className="refined-record-name">{item.title || item.name}</p>
      <div className="settings-dialog-actions"><button type="button" autoFocus disabled={busy} onClick={onClose}>Keep {noun}</button>
        <button type="button" className="refined-danger" disabled={busy} onClick={submit}>{busy ? "Deleting…" : `Delete ${noun}`}</button></div></>
      : <form onSubmit={submit}><label htmlFor={fieldId}>{moving ? "Project" : kind === "project" ? "Project name" : "Chat title"}</label>
        {moving ? <><select id={fieldId} autoFocus value={projectId} disabled={busy} onChange={(event) => setProjectId(event.target.value)}>
          <option value="">No project</option>{item.projectId && !chat.projects.items.some((project) => project.id === item.projectId)
            && <option value={item.projectId}>Current project</option>}
          {chat.projects.items.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select>
          {chat.projects.cursor && <p>Only the current project page is shown. Load more projects in navigation before moving to another page.</p>}</>
          : <input id={fieldId} type="text" autoFocus required maxLength={120} value={name} disabled={busy} autoComplete="off" onChange={(event) => setName(event.target.value)} />}
        <div className="settings-dialog-actions"><button type="button" disabled={busy} onClick={onClose}>Cancel</button>
          <button type="submit" disabled={busy || (!moving && !name.trim())}>{busy ? "Saving…" : moving ? "Move chat" : mode === "create" ? "Create project" : "Save changes"}</button></div>
      </form>}
    {error && <p role="alert">{error}</p>}
  </PreferenceDialog>;
}
