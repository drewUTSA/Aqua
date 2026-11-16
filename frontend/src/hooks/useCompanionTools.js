import { useEffect, useRef, useState } from "react";
import { getCompanionCapabilities, askCompanionHelp } from "../services/aquaClient.js";
import { assertHistory, captureHistory, subscribeHistory } from "../services/historyAuthority.js";
import { createCompanionToolsController, initialCompanionState } from "./companionToolsState.js";

export function useCompanionTools({ ownerId, csrfToken, targetId, onClose, onAuthFailure }) {
  const [state, setState] = useState(initialCompanionState), control = useRef(null), callbacks = useRef(null);
  callbacks.current = { onClose, onAuthFailure };
  useEffect(() => {
    let history;
    try { history = captureHistory(csrfToken); } catch { callbacks.current.onClose(); return; }
    const controller = createCompanionToolsController({ api: { menu: getCompanionCapabilities, help: askCompanionHelp },
      options: { csrfToken, historyContext: history }, assertCurrent: () => assertHistory(history), onState: setState,
      onInvalidated: () => callbacks.current.onClose(), onAuthFailure: () => callbacks.current.onAuthFailure?.() });
    control.current = { controller, ownerId, csrfToken, targetId };
    const unsubscribe = subscribeHistory(() => controller.invalidate());
    void controller.load();
    return () => { unsubscribe(); controller.close(); if (control.current?.controller === controller) control.current = null; };
  }, [ownerId, csrfToken, targetId]);
  const bindingMatches = () => control.current?.ownerId === ownerId && control.current?.csrfToken === csrfToken && control.current?.targetId === targetId;
  const current = () => bindingMatches() && control.current.controller.current();
  return { state: bindingMatches() ? state : initialCompanionState(),
    load: () => { if (current()) void control.current.controller.load(); },
    ask: (question) => { if (current()) void control.current.controller.ask(question); },
    edit: () => { if (current()) control.current.controller.edit(); },
    conflict: () => { if (current()) control.current.controller.conflict(); }, current };
}
