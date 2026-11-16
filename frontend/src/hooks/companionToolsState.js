// One explicit read at a time. No question/result persistence or tool execution.
export const initialCompanionState = () => ({ phase: "loading", menu: null, answer: null, error: "" });
const unavailable = "Reviewed Aqua help is not available on this server. You can close this window and keep using Aqua.";
const failed = "Aqua could not read the reviewed help. Your text has been kept. Try again when you are ready.";

export function createCompanionToolsController({ api, options, assertCurrent, onState, onInvalidated, onAuthFailure }) {
  let state = initialCompanionState(), active = true, sequence = 0, request = null;
  const abort = () => { sequence += 1; request?.abort(); request = null; };
  const close = () => { active = false; abort(); state = { phase: "closed", menu: null, answer: null, error: "" }; };
  const invalidate = () => { if (!active) return; close(); onInvalidated?.(); };
  const current = (ticket = sequence) => {
    if (!active || ticket !== sequence) return false;
    try { assertCurrent(); return true; } catch { invalidate(); return false; }
  };
  const publish = (next) => { if (current()) { state = next; onState(next); } };
  async function run(kind, question) {
    if (!current()) return;
    abort(); const ticket = sequence, controller = new AbortController(); request = controller;
    publish({ phase: kind === "menu" ? "loading" : "reading", menu: kind === "menu" ? null : state.menu, answer: null, error: "" });
    if (!current(ticket)) return;
    try {
      const value = kind === "menu" ? await api.menu({ ...options, signal: controller.signal }) : await api.help(question, { ...options, signal: controller.signal });
      if (!current(ticket) || controller.signal.aborted) return;
      publish(kind === "menu" ? { phase: "ready", menu: value, answer: null, error: "" }
        : { ...state, phase: value.status, answer: value, error: "" });
    } catch (error) {
      if (!current(ticket) || controller.signal.aborted || error?.name === "AbortError") return;
      if (error?.status === 401 || error?.code === "history_changed") { invalidate(); onAuthFailure?.(); return; }
      publish({ ...state, phase: error?.status === 404 ? "unavailable" : "error", answer: null,
        error: error?.status === 404 ? unavailable : failed });
    } finally { if (request === controller) request = null; }
  }
  return {
    load: () => run("menu"), ask: (question) => state.menu ? run("help", question) : Promise.resolve(),
    edit() { if (!current()) return; abort(); publish({ ...state, phase: state.menu ? "ready" : "loading", answer: null, error: "" }); },
    conflict() { publish({ ...state, phase: "error", answer: null, error: "The composer draft changed. Close help and review the current draft before replacing it." }); },
    current, invalidate, close, snapshot: () => state,
  };
}
