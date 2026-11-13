import { WorkspaceError } from "../services/workspaceClient.js";
import { assertHistory, historyHeaders } from "../services/historyAuthority.js";
import { assertUniqueJsonKeys } from "./strictJson.js";
import { deletionReply, deletionStart, DELETION_SCOPES } from "./dataDeletionContract.js";
const starts = new WeakSet();
const aborted = () => new DOMException("Request cancelled", "AbortError");
const invalid = () => new WorkspaceError("invalid_response");
function read(reader, signal) {
  if (signal.aborted) return Promise.reject(aborted());
  return new Promise((resolve, reject) => {
    const stop = () => { void reader.cancel().catch(() => {}); reject(aborted()); };
    signal.addEventListener("abort", stop, { once: true });
    reader.read().then(resolve, reject).finally(() => signal.removeEventListener("abort", stop));
  });
}
async function request(receipt, create, proof, { signal } = {}) {
  if (signal?.aborted) throw aborted();
  const context = receipt.context();
  if (create) assertHistory(receipt.history);
  const payload = create ? deletionStart({ intent_id: receipt.intent, scope: receipt.scope, proof_token: proof,
    confirmation: DELETION_SCOPES[receipt.scope].confirmation, receipt_token: receipt.token() }) : {};
  const controller = new AbortController(), cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(cancel, 15000); let reader; const chunks = [];
  try {
    const response = await fetch("/api/v1/me/data-deletions" + (create ? "" : "/by-intent/" + receipt.intent), {
      method: "POST", credentials: "same-origin", mode: "same-origin", cache: "no-store", redirect: "error", referrerPolicy: "strict-origin", signal: controller.signal,
      headers: { Accept: "application/json", "Content-Type": "application/json", "X-CSRF-Token": receipt.csrf,
        ...(create ? historyHeaders(receipt.history) : { "X-Aqua-Deletion-Receipt": receipt.token() }) }, body: JSON.stringify(payload)
    });
    if (controller.signal.aborted || !receipt.current()) { await response.body?.cancel(); throw aborted(); }
    if (response.redirected || !(create ? [200, 202] : [200]).includes(response.status)) {
      await response.body?.cancel();
      throw new WorkspaceError(({ 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_input", 429: "throttled" })[response.status] || "unavailable", response.status);
    }
    const length = response.headers.get("Content-Length");
    if (response.headers.get("Content-Type")?.split(";", 1)[0].trim() !== "application/json" || !response.body?.getReader
      || length !== null && (!/^\d{1,8}$/.test(length) || Number(length) > 16384)) { await response.body?.cancel(); throw invalid(); }
    reader = response.body.getReader(); let size = 0;
    while (true) {
      if (controller.signal.aborted || !receipt.current()) throw aborted();
      const { value, done } = await read(reader, controller.signal);
      if (controller.signal.aborted || !receipt.current()) { value?.fill?.(0); throw aborted(); }
      if (done) break;
      if (!(value instanceof Uint8Array) || !value.byteLength || chunks.length >= 1024 || (size += value.byteLength) > 16384) { value?.fill?.(0); throw invalid(); }
      chunks.push(value);
    }
    const bytes = new Uint8Array(size); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    try {
      const text = new TextDecoder("utf-8", { fatal: true }).decode(bytes); assertUniqueJsonKeys(text);
      const reply = deletionReply(JSON.parse(text), context, response.status);
      if (!receipt.accept(reply)) throw aborted();
      return reply;
    } catch (error) { if (error.name === "AbortError") throw error; throw invalid(); }
    finally { bytes.fill(0); }
  } catch (error) {
    if (signal?.aborted || !receipt.current()) throw aborted();
    if (error instanceof WorkspaceError || error.name === "AbortError") throw error;
    throw new WorkspaceError("unavailable");
  } finally {
    clearTimeout(timer); signal?.removeEventListener("abort", cancel);
    if (reader) { await reader.cancel().catch(() => {}); reader.releaseLock(); }
    for (const chunk of chunks) chunk.fill(0);
  }
}
export function startDataDeletion(receipt, proof, options) {
  if (!receipt.attempted() || starts.has(receipt)) throw new WorkspaceError("invalid_input", 422);
  starts.add(receipt);
  return request(receipt, true, proof, options);
}
export function reconcileDataDeletion(receipt, options) {
  if (!receipt.attempted()) throw new WorkspaceError("invalid_input", 422);
  return request(receipt, false, null, options);
}
