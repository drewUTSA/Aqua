// Ephemeral, single-flight display state. No persistence or analytical submission.
export const initialBankDemoState = () => ({ phase: "idle", context: null, selected: "", result: null, error: "" });
const copy = {
  unavailable: "The fictional bank demo is not enabled on this server. Aqua help and your composer are still available.",
  denied: "This fictional report is outside the current demo scope. Reload the available reports before continuing.",
  stale: "The demo source changed. Reload the available reports to read the current version.",
  error: "Aqua could not read the fictional report. Reload the available reports when you are ready.",
};

export function createBankDemoController({ api, options, assertCurrent, onState, onInvalidated, onAuthFailure }) {
  let state = initialBankDemoState(), active = true, sequence = 0, request = null;
  const abort = () => { sequence++; request?.abort(); request = null; };
  const close = () => { active = false; abort(); state = { ...initialBankDemoState(), phase: "closed" }; };
  const current = (ticket = sequence) => {
    if (!active || ticket !== sequence) return false;
    try { assertCurrent(); return true; } catch { close(); onInvalidated?.(); return false; }
  };
  const publish = next => { if (current()) { state = next; onState(next); } };
  async function run(kind) {
    if (!current() || ["loading", "reading"].includes(state.phase) || kind === "report" && (!state.context || !state.context.reports.some(report => report.id === state.selected))) return;
    const selected = state.selected, context = state.context;
    abort(); const ticket = sequence, controller = new AbortController(); request = controller;
    publish(kind === "context" ? { ...initialBankDemoState(), phase: "loading" }
      : { ...state, phase: "reading", result: null, error: "" });
    try {
      const value = kind === "context" ? await api.context({ ...options, signal: controller.signal })
        : await api.report(selected, context, { ...options, signal: controller.signal });
      if (!current(ticket) || controller.signal.aborted) return;
      publish(kind === "context" ? { ...initialBankDemoState(), phase: value.reports.length ? "ready" : "empty", context: value }
        : { ...state, phase: "ready", result: value });
    } catch (error) {
      if (!current(ticket) || controller.signal.aborted || error?.name === "AbortError") return;
      if (error?.status === 401 || error?.code === "history_changed") { close(); onInvalidated?.(); onAuthFailure?.(); return; }
      const phase = error?.status === 404 ? "unavailable" : error?.status === 403 ? "denied" : error?.status === 409 ? "stale" : "error";
      publish({ ...initialBankDemoState(), phase, error: copy[phase] });
    } finally { if (request === controller) request = null; }
  }
  return {
    load: () => run("context"), read: () => run("report"),
    select(id) {
      if (!current() || !state.context || !state.context.reports.some(report => report.id === id)) return;
      abort(); publish({ ...state, phase: "ready", selected: id, result: null, error: "" });
    },
    close, current, snapshot: () => state,
  };
}
