import { ACCOUNT_DEFAULTS, DEVICE_DEFAULTS, clone, equal, validateValues } from "./schema.js";

export function initialPreferences(device = DEVICE_DEFAULTS) {
  const values = { account: clone(ACCOUNT_DEFAULTS), device: clone(device) };
  return { saved: clone(values), draft: clone(values), revision: null, capabilities: {}, ready: false,
    loading: true, saving: false, error: "", status: "", conflict: false, needsReload: false, undo: null };
}
export const dirtyScopes = (state) => ({ account: !equal(state.saved.account, state.draft.account), device: !equal(state.saved.device, state.draft.device) });
export const isDirty = (state) => Object.values(dirtyScopes(state)).some(Boolean);
export function loadPreferences(state, response, { reapply = false } = {}) {
  return { ...state, saved: { ...state.saved, account: clone(response.values) },
    draft: { ...state.draft, account: reapply ? state.draft.account : clone(response.values) }, revision: response.revision,
    capabilities: response.capabilities, loading: false, ready: true, conflict: false, needsReload: false,
    error: "", status: reapply ? "Latest account preferences loaded. Review your draft, then save." : "", undo: null };
}
export function changePreference(state, scope, key, value) {
  const next = validateValues({ ...state.draft[scope], [key]: value }, scope);
  return { ...state, draft: { ...state.draft, [scope]: next }, error: "", status: "" };
}
export function cancelPreferences(state) {
  return { ...state, draft: clone(state.saved), error: "", status: "Unsaved changes discarded.", undo: null };
}
export function replaceDraft(state, changes, label) {
  const draft = { account: { ...state.draft.account, ...changes.account }, device: { ...state.draft.device, ...changes.device } };
  validateValues(draft.account, "account"); validateValues(draft.device, "device");
  return { ...state, draft, undo: { draft: clone(state.draft), label }, error: "", status: `${label} applied to draft. Save changes to keep it.` };
}
export function confirmScope(state, snapshot, scope, canonical) {
  // A completed request acknowledges its submitted values, never newer edits.
  const draft = Object.fromEntries(Object.entries(state.draft[scope]).map(([key, value]) =>
    [key, equal(value, snapshot[scope][key]) ? clone(canonical[key]) : value]));
  return { ...state, saved: { ...state.saved, [scope]: clone(canonical) }, draft: { ...state.draft, [scope]: draft } };
}
export function recoverAccountSave(state, snapshot, response) {
  if (equal(response.values, snapshot.account)) {
    return { outcome: "confirmed", state: { ...confirmScope(state, snapshot, "account", response.values),
      revision: response.revision, capabilities: response.capabilities, ready: true, conflict: false, needsReload: false } };
  }
  if (response.revision === snapshot.revision && equal(response.values, state.saved.account)) {
    return { outcome: "retryable", state: loadPreferences(state, response, { reapply: true }) };
  }
  // Readback after a lost response is observation, not permission to overwrite
  // another writer. Keep its authoritative saved values but require review of
  // the retained draft before any full-snapshot retry can use the new revision.
  return { outcome: "conflict", state: { ...loadPreferences(state, response, { reapply: true }),
    conflict: true, needsReload: true, status: "Account preferences changed elsewhere. Reload or review and reapply the draft before saving." } };
}
