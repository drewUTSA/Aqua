import { chatRecord, isRecord, messageRecord, pageRecord, projectRecord, promptRecord, requireContract, submissionRecord, validId } from "./workspaceContract.js";

// A requested history page has at most twenty server-capped 240kB results.
const MAX_BYTES = 6 * 1024 * 1024;
const COPY = { unauthenticated: "Your session has ended. Please sign in again.", forbidden: "This action is unavailable with your current access.",
  unavailable: "AQUA could not confirm this change. Check your connection and try again.", not_found: "This item is no longer available.",
  conflict: "This item changed elsewhere. Refresh it before trying again.", invalid_input: "Check the text and try again.",
  throttled: "Too many workspace actions. Wait before trying again.", invalid_response: "AQUA could not read the saved workspace safely." };
export class WorkspaceError extends Error {
  constructor(code, status = 0, retryAfter = null) { super(COPY[code] || COPY.unavailable); this.name = "WorkspaceError";
    this.code = Object.hasOwn(COPY, code) ? code : "unavailable"; this.status = status; this.retryAfter = retryAfter; }
}
export const operationId = () => globalThis.crypto.randomUUID();
const aborted = () => new DOMException("Request cancelled", "AbortError");
function idPath(id) { if (!validId(id)) throw new WorkspaceError("invalid_input"); return id; }
function query(values) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(values)) if (value !== undefined && value !== null && value !== "") params.set(key, String(value));
  return params.size ? `?${params}` : "";
}
async function readBody(response, signal) {
  const length = response.headers.get("Content-Length"), type = response.headers.get("Content-Type")?.split(";", 1)[0].trim();
  if (type !== "application/json" || (length !== null && (!/^\d{1,10}$/.test(length) || Number(length) > MAX_BYTES)) || !response.body?.getReader) {
    await response.body?.cancel(); throw new WorkspaceError("invalid_response");
  }
  const reader = response.body.getReader(), chunks = []; let bytes = 0;
  try {
    while (true) { if (signal.aborted) throw aborted(); const { value, done } = await reader.read(); if (signal.aborted) throw aborted();
      if (done) break; bytes += value.byteLength; if (bytes > MAX_BYTES) throw new WorkspaceError("invalid_response"); chunks.push(value); }
    const result = new Uint8Array(bytes); let offset = 0; for (const chunk of chunks) { result.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(result));
  } finally { await reader.cancel().catch(() => {}); reader.releaseLock(); }
}
export async function workspaceRequest(path, { method = "GET", body, csrfToken, signal, timeout = 15000,
  expectedStatuses = method === "DELETE" ? [204] : method === "POST" ? [200, 201] : [200] } = {}) {
  if (signal?.aborted) throw aborted();
  if (method !== "GET" && (!csrfToken || /[\r\n]/.test(csrfToken))) throw new WorkspaceError("unauthenticated", 401);
  const controller = new AbortController(), cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  const timer = setTimeout(cancel, timeout);
  try {
    const response = await fetch(`/api/v1${path}`, { method, credentials: "same-origin", mode: "same-origin", cache: "no-store", redirect: "error",
      referrerPolicy: "no-referrer", signal: controller.signal, headers: { Accept: "application/json", ...(method !== "GET" ? {
        "Content-Type": "application/json", "X-CSRF-Token": csrfToken } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}) });
    if (controller.signal.aborted) { await response.body?.cancel(); throw aborted(); }
    if (response.redirected || !expectedStatuses.includes(response.status)) {
      await response.body?.cancel();
      const retry = response.headers.get("Retry-After"), seconds = /^\d{1,5}$/.test(retry || "") ? Math.min(Number(retry), 86400) : null;
      throw new WorkspaceError(({ 401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict", 422: "invalid_input", 429: "throttled" })[response.status] || "unavailable", response.status, seconds);
    }
    return response.status === 204 ? null : await readBody(response, controller.signal);
  } catch (error) {
    if (signal?.aborted) throw aborted();
    if (error instanceof WorkspaceError) throw error;
    throw new WorkspaceError(controller.signal.aborted ? "unavailable" : "invalid_response");
  } finally { clearTimeout(timer); signal?.removeEventListener("abort", cancel); }
}
async function validated(path, options, normalize) {
  const body = await workspaceRequest(path, options);
  try { return normalize(body); } catch { throw new WorkspaceError("invalid_response"); }
}
export const listChats = ({ cursor, search, archived = false, projectId, ...options } = {}) => search
  ? validated("/chats/search", { ...options, method: "POST", body: { search, archived, limit: 20,
    ...(projectId ? { project_id: projectId } : {}), ...(cursor ? { cursor } : {}) } }, (body) => pageRecord(body, chatRecord))
  : validated(`/chats${query({ limit: 20, cursor, archived, project_id: projectId })}`, options, (body) => pageRecord(body, chatRecord));
export const getChat = (id, options) => validated(`/chats/${idPath(id)}`, options, (body) => chatRecord(body?.chat));
export const listMessages = (id, { cursor, ...options } = {}) => validated(`/chats/${idPath(id)}/messages${query({ limit: 20, cursor })}`, options, (body) => {
  const page = pageRecord(body, messageRecord, "older_cursor"); requireContract(page.items.every((item) => item.conversationId === id)); return page;
});
export const submitQuestion = ({ chatId, retryInputId, ...body }, options) => validated(chatId
  ? `/chats/${idPath(chatId)}/messages${retryInputId ? `/${idPath(retryInputId)}/retries` : ""}` : "/chats",
{ ...options, method: "POST", body, timeout: 120000, expectedStatuses: [200, 201, 202] }, (value) => {
  const result = submissionRecord(value); requireContract(result.request.clientId === body.client_request_id && (!chatId || result.chat.id === chatId)); return result;
});
export const updateChat = (id, body, options) => validated(`/chats/${idPath(id)}`, { ...options, method: "PATCH", body }, (value) => chatRecord(value?.chat));
export const deleteChat = (id, revision, options) => workspaceRequest(`/chats/${idPath(id)}${query({ revision })}`, { ...options, method: "DELETE" });
export const listProjects = ({ cursor, ...options } = {}) => validated(`/projects${query({ limit: 20, cursor })}`, options, (body) => pageRecord(body, projectRecord));
export const saveProject = (id, body, options) => validated(`/projects${id ? `/${idPath(id)}` : ""}`, { ...options, method: id ? "PATCH" : "POST", body }, (value) => projectRecord(value?.project));
export const deleteProject = (id, revision, options) => workspaceRequest(`/projects/${idPath(id)}${query({ revision })}`, { ...options, method: "DELETE" });
export const listPrompts = ({ cursor, ...options } = {}) => validated(`/me/saved-prompts${query({ limit: 20, cursor })}`, options, (body) => pageRecord(body, promptRecord));
export const savePrompt = (id, body, options) => validated(`/me/saved-prompts${id ? `/${idPath(id)}` : ""}`, { ...options, method: id ? "PATCH" : "POST", body }, (value) => promptRecord(value?.saved_prompt));
export const deletePrompt = (id, revision, options) => workspaceRequest(`/me/saved-prompts/${idPath(id)}${query({ revision })}`, { ...options, method: "DELETE" });
export const usePrompt = (id, body, options) => validated(`/me/saved-prompts/${idPath(id)}/uses`, { ...options, method: "POST", body }, (value) => promptRecord(value?.saved_prompt));
export const listStarters = (options) => validated("/starter-prompts", options, (body) => {
  requireContract(isRecord(body) && Array.isArray(body.items) && body.items.length <= 20 && body.items.every((item) => isRecord(item)
    && typeof item.id === "string" && typeof item.title === "string" && typeof item.prompt === "string" && item.prompt.length <= 4000));
  return body.items.map(({ id, title, prompt }) => ({ id, title, prompt }));
});
