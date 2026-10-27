import { workspaceRequest, WorkspaceError } from "./workspaceClient.js";
import { analysisSnapshot, eventParser } from "./analysisProtocol.js";
import { validId } from "./workspaceContract.js";

const abortError = () => new DOMException("Observation stopped", "AbortError");
function path(id) { if (!validId(id)) throw new WorkspaceError("invalid_input"); return `/analysis-requests/${id}`; }
async function snapshotRequest(id, options, suffix = "") {
  const body = await workspaceRequest(path(id) + suffix, options);
  try { return analysisSnapshot(body, id); } catch { throw new WorkspaceError("invalid_response"); }
}
export const getAnalysis = (id, options) => snapshotRequest(id, { ...options, method: "GET", body: undefined, expectedStatuses: [200] });
export const cancelAnalysis = (id, options) => snapshotRequest(id, { ...options, method: "POST", body: {}, expectedStatuses: [200, 202],
}, "/cancel");

export async function watchAnalysis(id, { sequence = 0, signal, onEvent, onOpen } = {}) {
  const endpoint = path(id);
  if (!Number.isSafeInteger(sequence) || sequence < 0) throw new WorkspaceError("invalid_input");
  if (signal?.aborted) throw abortError();
  const controller = new AbortController(), abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 65000);
  let reader;
  try {
    const response = await fetch(`/api/v1${endpoint}/events`, { method: "GET", credentials: "same-origin", mode: "same-origin",
      cache: "no-store", redirect: "error", referrerPolicy: "no-referrer", signal: controller.signal,
      headers: { Accept: "text/event-stream", ...(sequence ? { "Last-Event-ID": `${id}:${sequence}` } : {}) } });
    if (controller.signal.aborted) { await response.body?.cancel(); throw abortError(); }
    if (response.redirected || response.status !== 200 || response.headers.get("Content-Type")?.split(";", 1)[0].trim() !== "text/event-stream" || !response.body?.getReader) {
      await response.body?.cancel();
      throw new WorkspaceError(({ 401: "unauthenticated", 403: "forbidden", 404: "not_found" })[response.status] || "unavailable", response.status);
    }
    reader = response.body.getReader(); onOpen?.();
    const decoder = new TextDecoder("utf-8", { fatal: true }), consume = eventParser(id, onEvent);
    let bytes = 0;
    while (true) {
      const { value, done } = await reader.read();
      if (controller.signal.aborted) throw abortError();
      if (done) break;
      bytes += value.byteLength; if (bytes > 256 * 1024) throw new WorkspaceError("invalid_response");
      consume(decoder.decode(value, { stream: true }));
    }
    consume(decoder.decode());
  } catch (error) {
    if (signal?.aborted) throw abortError();
    if (error instanceof WorkspaceError) throw error;
    throw new WorkspaceError("invalid_response");
  } finally {
    clearTimeout(timer); signal?.removeEventListener("abort", abort);
    if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
  }
}
