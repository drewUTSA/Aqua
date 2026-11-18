import { useEffect, useRef, useState } from "react";
import { assertHistory, subscribeHistory } from "../../services/historyAuthority.js";
import { readResultBrief } from "./api.js";
import { createResultCompanionController, initialResultState } from "./state.js";

export function useResultCompanion({ binding, csrfToken, historyContext, onClose, onAuthFailure }) {
  const [state, setState] = useState(initialResultState), control = useRef(null), latest = useRef(null), callbacks = useRef(null);
  latest.current = { token: binding.token, ownerId: binding.ownerId, csrfToken, historyContext };
  callbacks.current = { onClose, onAuthFailure };
  useEffect(() => {
    const history = historyContext;
    try { assertHistory(history); } catch { callbacks.current.onClose(); return; }
    const expected = { token: binding.token, ownerId: binding.ownerId, csrfToken, historyContext };
    const assertCurrent = () => { assertHistory(history);
      if (Object.keys(expected).some(key => latest.current[key] !== expected[key])) throw new DOMException("Result changed", "AbortError"); };
    const controller = createResultCompanionController({ api: readResultBrief, binding,
      options: { ownerId: binding.ownerId, csrfToken, historyContext: history }, assertCurrent, onState: setState,
      onInvalidated: () => callbacks.current.onClose(), onAuthFailure: () => callbacks.current.onAuthFailure?.() });
    control.current = { ...expected, controller };
    const unsubscribe = subscribeHistory(() => { controller.close(); callbacks.current.onClose(); });
    void controller.load();
    return () => { unsubscribe(); controller.close(); if (control.current?.controller === controller) control.current = null; };
  }, [binding.token, binding.ownerId, csrfToken, historyContext]);
  const matches = () => control.current?.token === binding.token && control.current?.ownerId === binding.ownerId && control.current?.csrfToken === csrfToken
    && control.current?.historyContext === historyContext;
  return { state: matches() ? state : initialResultState(),
    current: () => matches() && control.current.controller.current(),
    retry: () => { if (matches()) void control.current.controller.load(); },
    select: index => { if (matches()) void control.current.controller.select(index); } };
}
