// One visit-local authority. Opaque revisions are compared only for equality;
// object identity fences responses and held intents across every authority change.
export const HISTORY_HEADER = "X-Aqua-History-Revision";
const REVISION = /^[0-9a-f]{64}$/;
let sequence = 0;
let authority = Object.freeze({ owner: null, csrf: null, revision: null, sequence });
const intents = new WeakMap(), sessions = new WeakMap(), listeners = new Set();
export class HistoryChangedError extends Error {
  constructor() { super("History changed. Reload the workspace before starting another action."); this.name = "HistoryChangedError"; this.code = "history_changed"; this.status = 409; }
}
const aborted = () => new DOMException("This action belongs to an earlier workspace.", "AbortError");
export function validHistoryRevision(value) { return typeof value === "string" && REVISION.test(value); }
function replace(next, notify) {
  authority = Object.freeze({ ...next, sequence: ++sequence });
  if (notify) for (const listener of listeners) listener(authority);
  return authority;
}
export function captureHistory(csrf) {
  if (authority.owner && csrf !== undefined && csrf !== authority.csrf) throw aborted();
  return authority;
}
export function assertHistory(context) { if (context !== authority) throw aborted(); return context; }
export function historyHeaders(context) { assertHistory(context); return context.revision ? { [HISTORY_HEADER]: context.revision } : {}; }
export function bindHistoryIntent(body, context = captureHistory()) {
  if (!body || typeof body !== "object") return assertHistory(context);
  if (!intents.has(body)) intents.set(body, context);
  return assertHistory(intents.get(body));
}
export function observeHistory(response, context) {
  assertHistory(context);
  const revision = response.headers?.get?.(HISTORY_HEADER) ?? null;
  if (revision !== null && !validHistoryRevision(revision)) {
    if (context.owner) replace({ owner: context.owner, csrf: context.csrf, revision: context.revision }, true);
    throw new HistoryChangedError();
  }
  // Anonymous/public requests cannot install a private owner's authority.
  if (!context.owner) return;
  if (revision && revision !== context.revision) {
    replace({ owner: context.owner, csrf: context.csrf, revision }, true);
    throw new HistoryChangedError();
  }
  if (response.ok && context.revision && revision === null) {
    replace({ owner: context.owner, csrf: context.csrf, revision: context.revision }, true);
    throw new HistoryChangedError();
  }
}
export function clearHistory() {
  if (authority.owner || authority.revision) replace({ owner: null, csrf: null, revision: null }, false);
}
export function subscribeHistory(listener) { listeners.add(listener); return () => listeners.delete(listener); }
export function stampSession(value, response, context) {
  if (value && typeof value === "object") sessions.set(value, { context, revision: response.headers?.get?.(HISTORY_HEADER) ?? null });
  return value;
}
export function copySessionStamp(source, target) { if (sessions.has(source)) sessions.set(target, sessions.get(source)); return target; }
export function activateSession(session) {
  const stamp = sessions.get(session);
  if (stamp) assertHistory(stamp.context);
  const revision = stamp?.revision ?? null;
  if (revision !== null && !validHistoryRevision(revision)) throw new HistoryChangedError();
  if (authority.owner === session.user.id && authority.csrf === session.csrf_token && authority.revision === revision) return authority.sequence;
  if (authority.owner === session.user.id && authority.csrf === session.csrf_token && authority.revision && !revision) throw new HistoryChangedError();
  return replace({ owner: session.user.id, csrf: session.csrf_token, revision }, false).sequence;
}
// Deletion metadata is purpose-limited and cannot reinstall a signed-out owner.
// Only a still-current initiating authority may adopt its confirmed revision.
export function deletionHistory(context, revision) {
  if (context !== authority || !context.owner || !validHistoryRevision(revision)) return false;
  if (context.revision !== revision) replace({ owner: context.owner, csrf: context.csrf, revision }, true);
  return true;
}
