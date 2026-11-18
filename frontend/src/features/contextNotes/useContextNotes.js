import { useEffect, useRef, useState } from "react";
import { assertHistory, captureHistory, subscribeHistory } from "../../services/historyAuthority.js";
import { operationId } from "../../services/workspaceClient.js";
import { listContextNotes, readContextNote, createContextNote, saveContextNote, forgetContextNote, prepareContextNote } from "./api.js";
import { createContextNotesController, initialContextNotesState } from "./state.js";

export function useContextNotes({ auth, targetId, assertParent, onClose, onApply }) {
  const ownerId = auth.user?.id, csrfToken = auth.csrfToken, canQuery = auth.canQuery;
  const [state, setState] = useState(initialContextNotesState), control = useRef(null), callbacks = useRef(null);
  callbacks.current = { assertParent, onClose, onApply, canQuery: auth.canQuery, refresh: auth.refresh };
  useEffect(() => {
    let history;
    try { if (!callbacks.current.assertParent()) throw Error("stale parent"); history = captureHistory(csrfToken); }
    catch { callbacks.current.onClose(); return; }
    const controller = createContextNotesController({ api: { list: listContextNotes, read: readContextNote, create: createContextNote,
      save: saveContextNote, forget: forgetContextNote, prepare: prepareContextNote }, options: { ownerId, csrfToken, historyContext: history }, createId: operationId,
      assertCurrent() { assertHistory(history); if (!callbacks.current.assertParent() || callbacks.current.canQuery !== canQuery) throw Error("stale parent"); }, onState: setState,
      onInvalidated: () => callbacks.current.onClose(), onAuthFailure: () => callbacks.current.refresh?.() });
    control.current = { controller, ownerId, csrfToken, targetId, canQuery };
    const unsubscribe = subscribeHistory(() => { controller.close(); callbacks.current.onClose(); });
    void controller.load();
    return () => { unsubscribe(); controller.close(); if (control.current?.controller === controller) control.current = null; };
  }, [ownerId, csrfToken, targetId, canQuery]);
  const matches = () => control.current?.ownerId === ownerId && control.current?.csrfToken === csrfToken && control.current?.targetId === targetId && control.current?.canQuery === canQuery;
  const invoke = (name, ...args) => { if (matches()) return control.current.controller[name](...args); };
  return { state: matches() ? state : initialContextNotesState(),
    load: () => invoke("load"), select: id => invoke("select", id), newNote: () => { if (auth.canQuery) invoke("newNote"); },
    edit: (field, value) => invoke("edit", field, value), save: () => { if (auth.canQuery) return invoke("save"); },
    confirmForget: show => invoke("confirmForget", show), forget: () => invoke("forget"), prepare: () => { if (auth.canQuery) return invoke("prepare"); },
    editDraft: value => invoke("editDraft", value), apply: () => { if (auth.canQuery) invoke("apply", value => callbacks.current.onApply(value)); } };
}
