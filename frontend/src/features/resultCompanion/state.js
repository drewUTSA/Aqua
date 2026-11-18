export const initialResultState = () => ({ phase: "idle", columnIndex: 0, reply: null, error: "", ticket: 0 });
const errors = {
  unavailable: "This saved result or the optional result companion is unavailable. Your original answer and composer remain available.",
  denied: "Aqua could not confirm your current access to this saved result. Refresh the conversation before trying again.",
  stale: "This saved result or its history changed. Refresh the conversation before trying again.",
  error: "Aqua could not read the saved-field check. You can retry when you are ready.",
};

export function createResultCompanionController({ api, binding, options, assertCurrent, onState, onInvalidated, onAuthFailure }) {
  let state = initialResultState(), active = true, sequence = 0, request = null;
  const abort = () => { sequence++; request?.abort(); request = null; };
  const close = () => { active = false; abort(); state = { ...initialResultState(), phase: "closed" }; };
  const current = (ticket = sequence) => {
    if (!active || ticket !== sequence) return false;
    try { assertCurrent(); return true; } catch { close(); onInvalidated?.(); return false; }
  };
  const publish = next => { if (current()) { state = next; onState(next); } };
  async function load(index = state.columnIndex) {
    if (!current() || !Number.isSafeInteger(index) || index < 0 || index >= binding.table.columns.length
      || state.phase === "loading" && index === state.columnIndex) return;
    abort(); const ticket = sequence, controller = new AbortController(); request = controller;
    publish({ ...initialResultState(), phase: "loading", columnIndex: index, ticket });
    try {
      const reply = await api(binding, index, { ...options, signal: controller.signal });
      if (!current(ticket) || controller.signal.aborted) return;
      publish({ phase: reply.brief.status, columnIndex: index, reply, error: "", ticket });
    } catch (error) {
      if (!current(ticket) || controller.signal.aborted) return;
      if (error?.status === 401 || error?.code === "history_changed") { close(); onInvalidated?.(); onAuthFailure?.(); return; }
      const phase = error?.status === 404 ? "unavailable" : error?.status === 403 ? "denied" : error?.status === 409 ? "stale" : "error";
      publish({ ...initialResultState(), columnIndex: index, ticket, phase, error: errors[phase] });
    } finally { if (request === controller) request = null; }
  }
  return { load, select: index => load(index), close, current, snapshot: () => state };
}
