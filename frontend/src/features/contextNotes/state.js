import { validNoteFields, validNoteDraft } from "./contract.js";

const emptyEditor = () => ({ kind: "note", label: "", body: "" });
export const initialContextNotesState = () => ({ phase: "idle", library: null, selected: null, note: null, editor: null, prepared: null,
  draft: "", confirmingForget: false, error: "", notice: "" });
const metadata = note => ({ id: note.id, revision: note.revision, availability: "available", label: note.label, kind: note.kind,
  created_at: note.created_at, updated_at: note.updated_at });
export const noteEditorDirty = state => Boolean(state.editor && (!state.note || ["kind", "label", "body"].some(key => state.editor[key] !== state.note[key])));
const busy = state => ["loading", "reading", "creating", "saving", "forgetting", "preparing"].includes(state.phase);

// All held text is local to this dialog. Uncertain writes require an explicit read, never a mutation retry.
export function createContextNotesController({ api, options, assertCurrent, createId, onState, onInvalidated, onAuthFailure }) {
  let state = initialContextNotesState(), active = true, sequence = 0, request = null;
  const abort = () => { sequence++; request?.abort(); request = null; };
  const close = () => { active = false; abort(); state = { ...initialContextNotesState(), phase: "closed" }; };
  const current = (ticket = sequence) => {
    if (!active || sequence !== ticket) return false;
    try { assertCurrent(); return true; } catch { close(); onInvalidated?.(); return false; }
  };
  const publish = next => { if (current()) { state = next; onState(next); } };
  const usable = () => current() && state.library && state.phase === "ready";
  async function run(action, call, success) {
    if (!current() || busy(state)) return;
    abort(); const ticket = sequence, controller = new AbortController(); request = controller;
    publish({ ...state, phase: action, error: "", notice: "", prepared: null, draft: "", confirmingForget: false,
      ...(action === "forgetting" ? { note: null, editor: null } : {}) });
    try {
      const value = await call({ ...options, signal: controller.signal });
      if (!current(ticket) || controller.signal.aborted) return;
      publish(success(value));
    } catch (error) {
      if (!current(ticket) || controller.signal.aborted || error?.name === "AbortError") return;
      if (error?.status === 401 || error?.code === "history_changed") { close(); onInvalidated?.(); onAuthFailure?.(); return; }
      const unavailable = action === "loading" && error?.status === 404;
      const message = unavailable ? "Saved notes are not enabled on this server. Your composer is still available."
        : error?.status === 409 ? "Saved context or access changed. Reload the library before continuing. Your composer was kept."
          : ["creating", "saving", "forgetting"].includes(action) ? "Aqua could not confirm this change. Reload the library to check its current state before another change."
            : "Aqua could not read saved context safely. Reload the library before continuing.";
      publish({ ...initialContextNotesState(), phase: unavailable ? "unavailable" : "blocked", error: message });
    } finally { if (request === controller) request = null; }
  }
  function acceptNote(value, notice) {
    const note = value.note, item = metadata(note), items = [item, ...state.library.items.filter(row => row.id !== note.id)];
    return { ...initialContextNotesState(), phase: "ready", library: { ...state.library, items }, selected: item, note,
      editor: { kind: note.kind, label: note.label, body: note.body }, notice };
  }
  return {
    load() {
      if (!current() || busy(state)) return;
      publish(initialContextNotesState());
      return run("loading", api.list, value => ({ ...initialContextNotesState(), phase: "ready", library: value }));
    },
    select(id) {
      if (!usable()) return;
      const selected = state.library.items.find(item => item.id === id); if (!selected) return;
      abort(); publish({ ...initialContextNotesState(), phase: "ready", library: state.library, selected });
      if (selected.availability !== "available") return;
      return run("reading", opts => api.read(selected, state.library.scope, opts), value => acceptNote(value, ""));
    },
    newNote() {
      if (!usable() || !state.library.scope.can_use || state.library.items.length >= 20) return;
      abort(); publish({ ...initialContextNotesState(), phase: "ready", library: state.library, editor: emptyEditor() });
    },
    edit(field, value) {
      if (!usable() || !state.editor || !["kind", "label", "body"].includes(field) || typeof value !== "string") return;
      // Bound even injected UI events; invalid text remains visible for explicit correction.
      if (value.length > (field === "body" ? 2000 : field === "label" ? 240 : 20)) return;
      publish({ ...state, editor: { ...state.editor, [field]: value }, prepared: null, draft: "", confirmingForget: false, notice: "", error: "" });
    },
    save() {
      if (!usable() || !state.library.scope.can_use || !validNoteFields(state.editor) || !noteEditorDirty(state)) return;
      const fields = { ...state.editor }, selected = state.note, scope = state.library.scope;
      if (!selected && state.library.items.length >= 20) return;
      return run(selected ? "saving" : "creating", opts => selected ? api.save(selected, fields, scope, opts) : api.create(fields, scope, createId(), opts),
        value => acceptNote(value, selected ? "Saved your correction." : "Saved your note."));
    },
    confirmForget(show) { if (usable() && state.selected) publish({ ...state, confirmingForget: Boolean(show), prepared: null, draft: "" }); },
    forget() {
      if (!usable() || !state.selected || !state.confirmingForget) return;
      const selected = state.selected, library = state.library;
      return run("forgetting", opts => api.forget(selected, library.scope, opts), () => ({ ...initialContextNotesState(), phase: "ready",
        library: { ...library, items: library.items.filter(item => item.id !== selected.id) }, notice: "Forgot this library entry. Copies already sent in chat history are unchanged." }));
    },
    prepare() {
      if (!usable() || !state.library.scope.can_use || !state.note || noteEditorDirty(state)) return;
      const selected = state.note, scope = state.library.scope;
      return run("preparing", opts => api.prepare(selected, scope, opts), value => ({ ...state, phase: "ready", prepared: value, draft: value.draft, error: "" }));
    },
    editDraft(value) {
      if (!usable() || !state.prepared || typeof value !== "string" || value.length > 2000) return;
      publish({ ...state, draft: value, error: "" });
    },
    apply(onApply) {
      if (!usable() || !state.library.scope.can_use || !state.note || !state.prepared || !validNoteDraft(state.draft) || noteEditorDirty(state)
        || state.prepared.scope.id !== state.library.scope.id || state.prepared.source.id !== state.note.id || state.prepared.source.revision !== state.note.revision) return false;
      if (onApply(state.draft) === true) return true;
      publish({ ...state, prepared: null, draft: "", error: "The composer changed. Close Aqua tools and start again; your current draft was kept." }); return false;
    },
    close, current, snapshot: () => state,
  };
}
