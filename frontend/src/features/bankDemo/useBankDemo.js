import { useEffect, useRef, useState } from "react";
import { assertHistory, captureHistory, subscribeHistory } from "../../services/historyAuthority.js";
import { bankDemoContext, bankDemoReport } from "./api.js";
import { createBankDemoController, initialBankDemoState } from "./state.js";

export function useBankDemo({ ownerId, csrfToken, targetId, onClose, onAuthFailure }) {
  const [state, setState] = useState(initialBankDemoState), control = useRef(null), callbacks = useRef(null);
  callbacks.current = { onClose, onAuthFailure };
  useEffect(() => {
    let history;
    try { history = captureHistory(csrfToken); } catch { callbacks.current.onClose(); return; }
    const controller = createBankDemoController({ api: { context: bankDemoContext, report: bankDemoReport },
      options: { ownerId, csrfToken, historyContext: history }, assertCurrent: () => assertHistory(history), onState: setState,
      onInvalidated: () => callbacks.current.onClose(), onAuthFailure: () => callbacks.current.onAuthFailure?.() });
    control.current = { controller, ownerId, csrfToken, targetId };
    const unsubscribe = subscribeHistory(() => { controller.close(); callbacks.current.onClose(); });
    void controller.load();
    return () => { unsubscribe(); controller.close(); if (control.current?.controller === controller) control.current = null; };
  }, [ownerId, csrfToken, targetId]);
  const matches = () => control.current?.ownerId === ownerId && control.current?.csrfToken === csrfToken && control.current?.targetId === targetId;
  return { state: matches() ? state : initialBankDemoState(),
    load: () => { if (matches()) void control.current.controller.load(); },
    read: requirements => { if (matches()) void control.current.controller.read(requirements); },
    select: id => { if (matches()) control.current.controller.select(id); } };
}
