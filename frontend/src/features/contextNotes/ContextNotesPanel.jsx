import React, { useId } from "react";
import { noteBytes, validNoteBody, validNoteDraft, validNoteLabel } from "./contract.js";
import { noteEditorDirty } from "./state.js";
import { useContextNotes } from "./useContextNotes.js";
import "./context-notes.css";

export function ContextNotesContent({ state, canQuery = false, onReload, onSelect, onNew, onEdit, onSave, onConfirmForget, onForget, onPrepare, onDraft, onApply }) {
  const prefix = useId(), library = state.library, editor = state.editor;
  const busy = ["loading", "reading", "creating", "saving", "forgetting", "preparing"].includes(state.phase);
  const usable = Boolean(library?.scope.can_use && canQuery), dirty = noteEditorDirty(state);
  const labelValid = Boolean(editor && validNoteLabel(editor.label)), bodyValid = Boolean(editor && validNoteBody(editor.body));
  return <section className="context-notes" aria-label="User-saved context" data-context-notes>
    <h3>Your saved context</h3>
    <p>Keep a note or your own metric definition for later. These are user-saved, unverified statements; they do not change result facts or units.</p>
    <p>Nothing is added to a question automatically. Prepare a note, review or edit its draft, apply it to the composer, then choose Send separately.</p>
    {["idle", "loading"].includes(state.phase) && <p role="status">Reading your saved-note list…</p>}
    {state.error && <p role="alert" className="context-notes__error">{state.error}</p>}
    {state.notice && <p role="status">{state.notice}</p>}
    {!busy && <button type="button" onClick={onReload} data-notes-reload>{library ? "Reload saved notes" : "Check saved notes availability"}</button>}
    {library && <>
      <p>{library.items.length} of 20 saved notes. Only notes for your current access can be read or used.</p>
      {!usable && <p role="status">Current dataset access is needed to create, edit or use notes. You can still forget an entry.</p>}
      {library.items.length === 0 ? <p>No notes saved yet. Save context you want to select again later.</p>
        : <ul className="context-notes__list" aria-label="Saved-note library">{library.items.map(item => <li key={item.id}>
          <button type="button" data-notes-select={item.id} aria-pressed={state.selected?.id === item.id} disabled={busy}
            onClick={() => onSelect(item.id)}>{item.label}{item.availability === "unavailable" ? " — forget only" : ""}</button>
        </li>)}</ul>}
      <button type="button" disabled={busy || !usable || library.items.length >= 20} onClick={onNew} data-notes-new>New saved note</button>
      {library.items.length >= 20 && <p>Forget an entry before saving another note.</p>}
    </>}
    {state.phase === "reading" && <p role="status">Reading this note’s current text…</p>}
    {editor && <form className="companion-tools__guide" onSubmit={event => { event.preventDefault(); onSave(); }} data-notes-editor>
      <h4>{state.note ? "Review or correct your saved note" : "Save a new note"}</h4>
      <label htmlFor={`${prefix}-kind`}>Type</label>
      <select id={`${prefix}-kind`} value={editor.kind} disabled={busy || !usable} onChange={event => onEdit("kind", event.target.value)} data-notes-kind>
        <option value="note">Note — unverified</option><option value="metric_definition">My metric definition — unverified</option>
      </select>
      <label htmlFor={`${prefix}-label`}>Label</label>
      <input id={`${prefix}-label`} value={editor.label} maxLength={240} disabled={busy || !usable} onChange={event => onEdit("label", event.target.value)}
        aria-invalid={Boolean(editor.label && !labelValid)} aria-describedby={`${prefix}-label-help`} autoComplete="off" data-notes-label />
      <p id={`${prefix}-label-help`}>{[...editor.label].length}/120 characters · {noteBytes(editor.label)}/512 bytes. No leading or trailing spaces.</p>
      {editor.label && !labelValid && <p role="alert">Use a label within both limits, without hidden or control characters.</p>}
      <label htmlFor={`${prefix}-body`}>Saved text</label>
      <textarea id={`${prefix}-body`} value={editor.body} maxLength={2000} rows={5} disabled={busy || !usable} onChange={event => onEdit("body", event.target.value)}
        aria-invalid={Boolean(editor.body && !bodyValid)} aria-describedby={`${prefix}-body-help`} autoComplete="off" data-notes-body />
      <p id={`${prefix}-body-help`}>{editor.body.length}/2000 text units · {noteBytes(editor.body)}/2048 bytes. Some characters use two text units; line breaks and tabs are allowed.</p>
      {editor.body && !bodyValid && <p role="alert">Use nonblank text within both limits, without hidden formatting or other control characters.</p>}
      <button type="submit" disabled={busy || !usable || !labelValid || !bodyValid || !dirty} data-notes-save>{state.phase === "creating" || state.phase === "saving" ? "Saving…" : state.note ? "Save correction" : "Save note"}</button>
      {dirty && state.note && <p>Save the correction before preparing this note. Your composer is unchanged.</p>}
      {state.note && <button type="button" disabled={busy || !usable || dirty} onClick={onPrepare} data-notes-prepare>{state.phase === "preparing" ? "Preparing…" : "Prepare for composer"}</button>}
    </form>}
    {state.selected && <div className="context-notes__forget">
      {state.selected.availability === "unavailable" && <p>This saved entry is unavailable with your current access. Its earlier label and text are not shown.</p>}
      {state.confirmingForget ? <>
        <p>Forget this library entry? This removes its saved text. Copies you already sent remain in chat history.</p>
        <div className="companion-tools__choice"><button type="button" onClick={onForget} disabled={busy} data-notes-forget-confirm>Forget saved entry</button>
          <button type="button" onClick={() => onConfirmForget(false)} disabled={busy}>Keep entry</button></div>
      </> : <button type="button" onClick={() => onConfirmForget(true)} disabled={busy} data-notes-forget>Forget this entry…</button>}
    </div>}
    {state.phase === "forgetting" && <p role="status">Forgetting the saved library entry…</p>}
    {state.prepared && <section className="companion-tools__guide" data-notes-preview>
      <h4>Review your composer draft</h4><p>User-saved, unverified source: {state.prepared.source.label} · revision {state.prepared.source.revision}</p>
      <label htmlFor={`${prefix}-draft`}>Editable draft</label>
      <textarea id={`${prefix}-draft`} value={state.draft} maxLength={2000} rows={5} onChange={event => onDraft(event.target.value)}
        aria-invalid={!validNoteDraft(state.draft)} aria-describedby={`${prefix}-draft-help`} data-notes-draft />
      <p id={`${prefix}-draft-help`}>{state.draft.length}/2000 text units · {noteBytes(state.draft)}/8000 bytes. Applying replaces the composer draft; nothing is sent.</p>
      {!validNoteDraft(state.draft) && <p role="alert">Use nonblank plain text within the draft limits.</p>}
      <button type="button" onClick={onApply} disabled={busy || !usable || !validNoteDraft(state.draft)} data-notes-apply>Apply to composer draft</button>
      <p>If you later choose Send, this text uses your configured model or provider and becomes part of chat history. Forgetting the note does not remove that copy.</p>
    </section>}
  </section>;
}

export default function ContextNotesPanel(props) {
  const notes = useContextNotes(props);
  return <ContextNotesContent state={notes.state} canQuery={props.auth.canQuery} onReload={notes.load} onSelect={notes.select} onNew={notes.newNote}
    onEdit={notes.edit} onSave={notes.save} onConfirmForget={notes.confirmForget} onForget={notes.forget} onPrepare={notes.prepare} onDraft={notes.editDraft} onApply={notes.apply} />;
}
