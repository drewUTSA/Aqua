import React, { useEffect, useRef, useState } from "react";
import { operationId } from "../../services/aquaClient.js";

export default function WorkspaceEditor({ kind, item, projects = [], onSave, onDelete, onClose }) {
  const dialog = useRef(null), clientId = useRef(operationId()), lock = useRef(false);
  const [name, setName] = useState(item?.title || item?.label || item?.name || ""), [prompt, setPrompt] = useState(item?.prompt || ""),
    [pinned, setPinned] = useState(item?.pinned || false), [archived, setArchived] = useState(item?.archived || false),
    [projectId, setProjectId] = useState(item?.projectId || ""), [busy, setBusy] = useState(false), [confirm, setConfirm] = useState(false), [failure, setFailure] = useState("");
  useEffect(() => { dialog.current?.showModal(); return () => dialog.current?.close(); }, []);
  const save = async (event) => { event.preventDefault(); if (lock.current) return; lock.current = true; setBusy(true); setFailure("");
    const values = kind === "prompt" ? { label: name.trim(), prompt: prompt.trim(), pinned }
      : kind === "chat" ? { title: name.trim(), project_id: projectId || null, archived } : { name: name.trim(), archived };
    const okay = await onSave(values, clientId.current); lock.current = false; setBusy(false);
    if (okay) onClose(); else setFailure("The change was not confirmed. Your text is preserved; refresh the item if it changed elsewhere."); };
  const remove = async () => { if (lock.current) return; lock.current = true; setBusy(true);
    const okay = await onDelete(); lock.current = false; setBusy(false); if (okay) onClose(); else setFailure("Deletion was not confirmed. Refresh and try again."); };
  const noun = kind === "prompt" ? "saved prompt" : kind;
  return <dialog ref={dialog} className="workspace-editor" aria-labelledby="workspace-editor-title" onCancel={(event) => { if (busy) event.preventDefault(); else onClose(); }}>
    <h2 id="workspace-editor-title">{confirm ? `Delete ${noun}?` : `${item ? "Edit" : "New"} ${noun}`}</h2>
    {confirm ? <><p>{kind === "project" ? "The project will be removed. Its chats stay in your workspace without a project."
      : `This permanently removes this ${noun}${kind === "chat" ? " and its saved messages and results" : ""}.`}</p>
      <div className="workspace-editor__actions"><button type="button" disabled={busy} onClick={remove}>Confirm delete</button><button type="button" disabled={busy} onClick={() => setConfirm(false)}>Keep {noun}</button></div></>
      : <form onSubmit={save}><label>{kind === "chat" ? "Chat title" : kind === "prompt" ? "Prompt label" : "Project name"}<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} disabled={busy} autoFocus /></label>
        {kind === "prompt" && <><label>Prompt<textarea required maxLength={2000} rows={5} value={prompt} onChange={(event) => setPrompt(event.target.value)} disabled={busy} /></label>
          <label className="workspace-editor__check"><input type="checkbox" checked={pinned} onChange={(event) => setPinned(event.target.checked)} disabled={busy} />Pin this prompt</label></>}
        {kind === "chat" && <label>Project<select value={projectId} onChange={(event) => setProjectId(event.target.value)} disabled={busy}><option value="">No project</option>
          {projectId && !projects.some((project) => project.id === projectId) && <option value={projectId}>Current project</option>}
          {projects.map((project) => <option key={project.id} value={project.id}>{project.name}</option>)}</select></label>}
        {item && kind === "chat" && <label className="workspace-editor__check"><input type="checkbox" checked={archived} onChange={(event) => setArchived(event.target.checked)} disabled={busy} />Archived</label>}
        <div className="workspace-editor__actions"><button type="submit" disabled={busy || !name.trim() || (kind === "prompt" && !prompt.trim())}>{busy ? "Saving…" : "Save"}</button>
          <button type="button" disabled={busy} onClick={onClose}>Cancel</button>{item && <button type="button" disabled={busy} onClick={() => setConfirm(true)}>Delete {noun}</button>}</div>
      </form>}
    {failure && <p role="alert">{failure}</p>}
  </dialog>;
}
