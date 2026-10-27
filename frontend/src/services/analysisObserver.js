import { getAnalysis, watchAnalysis } from "./analysisClient.js";
import { terminalAnalysis } from "./workspaceContract.js";
import { WorkspaceError } from "./workspaceClient.js";

export const observationAborted = () => new DOMException("Observation stopped", "AbortError");
export function observationDelay(milliseconds, signal) {
  if (signal.aborted) return Promise.reject(observationAborted());
  return new Promise((resolve, reject) => {
    const abort = () => { clearTimeout(timer); reject(observationAborted()); };
    const timer = setTimeout(() => { signal.removeEventListener("abort", abort); resolve(); }, milliseconds);
    signal.addEventListener("abort", abort, { once: true });
  });
}

// At most one stream and one snapshot read belong to an observer. Events never
// carry result content; terminal/gapped metadata reconciles through a fresh GET.
export async function observeAnalysis(id, { signal, onSnapshot, onProgress, onConnection,
  read = getAnalysis, watch = watchAnalysis, pause = observationDelay, now = Date.now } = {}) {
  const started = now(); let version = 0, sequence = 0, terminal = false, deadline = started + 600000;
  const current = () => { if (signal.aborted) throw observationAborted(); };
  const accept = (snapshot) => {
    current(); const next = snapshot.request;
    if (next.id !== id) throw new WorkspaceError("invalid_response");
    if (terminal || next.version < version || next.version === version && next.sequence < sequence) return;
    version = next.version; sequence = next.sequence; terminal = terminalAnalysis(next.state);
    if (next.deadlineAt !== null) deadline = Math.min(deadline, next.deadlineAt + 30000);
    onSnapshot(snapshot);
  };
  const refresh = async () => { const snapshot = await read(id, { signal }); current(); accept(snapshot); };
  const fatal = (error) => [401, 403, 404].includes(error.status);
  onConnection("connecting");
  await refresh();
  if (terminal) return;
  let polling = false, emptyStreams = 0;
  while (!terminal && now() < deadline && !polling) {
    current(); const stream = new AbortController(), stop = () => stream.abort();
    signal.addEventListener("abort", stop, { once: true });
    let pending = null, reconciled = false, failure = null;
    const reconcile = () => {
      if (reconciled) return;
      reconciled = true;
      pending = refresh().catch((error) => { failure = error; }).finally(() => stream.abort());
    };
    let received = false;
    try {
      await watch(id, { signal: stream.signal, sequence, onOpen: () => onConnection("live"), onEvent: (event) => {
        current(); received = true;
        if (event.requestId !== id) throw new WorkspaceError("invalid_response");
        if (event.version < version || event.version === version && event.sequence <= sequence) return;
        if (event.snapshotRequired || event.sequence !== sequence + 1 || terminalAnalysis(event.state)) { reconcile(); return; }
        version = event.version; sequence = event.sequence; onProgress(event);
      } });
      if (pending) await pending;
      if (failure) throw failure;
      if (!reconciled) await refresh();
      // A server closing without metadata must not cause a reconnect spin.
      emptyStreams = received ? 0 : emptyStreams + 1;
      if (emptyStreams >= 2) polling = true;
      else if (!terminal) await pause(1000, signal);
    } catch (error) {
      if (pending) await pending;
      current(); if (failure && fatal(failure)) throw failure;
      if (terminal) return;
      if (fatal(error)) throw error;
      if (reconciled && !failure) { await pause(1000, signal); continue; }
      polling = true;
    } finally { signal.removeEventListener("abort", stop); stream.abort(); }
  }
  let failures = 0;
  while (!terminal && now() < deadline) {
    current(); onConnection(failures ? "offline" : "polling");
    await pause(Math.min(2000 * 2 ** failures, 15000), signal);
    try { await refresh(); failures = 0; }
    catch (error) { current(); if (fatal(error) || ++failures >= 6) throw error; }
  }
  current(); if (!terminal) throw new WorkspaceError("unavailable");
}
