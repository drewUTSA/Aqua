import React, { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { ACCOUNT_DEFAULTS, DEVICE_DEFAULTS, clone, validateValues } from "./schema.js";
import { readDevicePreferences, saveDevicePreferences } from "./deviceStore.js";
import { readPreferences, writePreferences } from "./preferenceClient.js";
import { cancelPreferences, changePreference, confirmScope, dirtyScopes, initialPreferences, isDirty, loadPreferences, recoverAccountSave, replaceDraft } from "./preferenceState.js";
import PreferenceDialog from "./PreferenceDialog.jsx";

const fallbackState = initialPreferences();
const FALLBACK = { ...fallbackState, loading: false, effective: { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS }, dirty: false,
  change() {}, cancel() {}, persistDeviceValue: () => false, save: async () => false, requestLeave: async (next) => next(), reload: async () => false };
const Context = createContext(FALLBACK);
export const usePreferences = () => useContext(Context);
const errorCopy = (error) => error?.status === 401 ? "Your session ended. Sign in again to save account preferences."
  : error?.status === 409 ? "Account preferences changed or use a newer schema. Reload before saving."
    : error?.status === 429 ? "Too many preference changes. Wait a minute before retrying."
      : "AQUA could not confirm account preferences. Reload to check their saved state.";

export function PreferencesProvider({ auth, previewEnabled = false, registerGuard, children }) {
  const owner = auth.demoMode ? "demo" : auth.user?.id;
  const authRef = useRef(auth); authRef.current = auth;
  const [deviceInfo] = useState(() => readDevicePreferences(owner));
  const [state, setState] = useState(() => initialPreferences(deviceInfo.values));
  const current = useRef(state), active = useRef(null), alive = useRef(true), generation = useRef(0);
  const [leaveOpen, setLeaveOpen] = useState(false), leave = useRef(null);
  const update = useCallback((transform) => {
    if (!alive.current) return;
    current.current = typeof transform === "function" ? transform(current.current) : transform;
    setState(current.current);
  }, []);
  const sessionFailure = (error) => {
    if (error?.status !== 401) return;
    generation.current++; active.current?.abort();
    update((value) => ({ ...value, saving: false, loading: false, ready: false, error: errorCopy(error) }));
    void authRef.current.refresh?.();
  };
  const reload = useCallback(async ({ reapply = false } = {}) => {
    if (authRef.current.demoMode) {
      update((value) => ({ ...value, loading: false, ready: true, revision: 1, status: "Demo preferences apply to this visit only." }));
      return true;
    }
    if (current.current.saving || authRef.current.status !== "authenticated") return false;
    const ticket = ++generation.current;
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    update((value) => ({ ...value, loading: true, error: "" }));
    try {
      const response = await readPreferences({ signal: controller.signal });
      if (!alive.current || ticket !== generation.current) return false;
      update((value) => loadPreferences(value, response, { reapply })); return true;
    } catch (error) {
      if (!alive.current || ticket !== generation.current || controller.signal.aborted) return false;
      update((value) => ({ ...value, loading: false, error: errorCopy(error), needsReload: true }));
      sessionFailure(error); return false;
    }
  }, [update]);
  useEffect(() => {
    alive.current = true; void reload();
    return () => { alive.current = false; generation.current++; active.current?.abort(); leave.current?.resolve(false); };
  }, [owner, reload]);
  useEffect(() => {
    if (!auth.demoMode && auth.status !== "authenticated") {
      const interrupted = current.current.loading || current.current.saving;
      generation.current++; active.current?.abort();
      update((value) => ({ ...value, loading: false, saving: false,
        ...(interrupted ? { needsReload: true, error: "Preference loading or saving was paused while sign-in was checked. Reload account preferences before saving." } : {}) }));
    }
    // Reauthentication must not silently rebase a dirty draft onto another
    // device's revision. Reload/reapply remains a deliberate review action.
  }, [auth.demoMode, auth.status, update]);
  const change = useCallback((scope, key, value) => {
    if (current.current.saving || scope === "account" && !current.current.ready
      || !authRef.current.demoMode && authRef.current.status !== "authenticated") return;
    update((currentState) => changePreference(currentState, scope, key, value));
  }, [update]);
  const cancel = useCallback(() => { if (!current.current.saving) update(cancelPreferences); }, [update]);
  const applyDraft = useCallback((changes, label) => {
    if (!current.current.saving) update((value) => replaceDraft(value, changes, label));
  }, [update]);
  const undoDraft = useCallback(() => {
    if (current.current.undo && !current.current.saving) update((value) => ({ ...value, draft: clone(value.undo.draft), undo: null, status: "Draft restored.", error: "" }));
  }, [update]);
  const save = useCallback(async () => {
    const before = current.current;
    if (before.saving || !authRef.current.demoMode && authRef.current.status !== "authenticated") return false;
    const targeted = dirtyScopes(before);
    if (!targeted.account && !targeted.device) return true;
    const snapshot = { ...clone(before.draft), revision: before.revision }, ticket = ++generation.current;
    const messages = [], failures = [];
    active.current?.abort(); const controller = new AbortController(); active.current = controller;
    update((value) => ({ ...value, saving: true, status: "", error: "" }));
    const isCurrent = () => alive.current && generation.current === ticket && !controller.signal.aborted;
    if (targeted.account) {
      if (authRef.current.demoMode) {
        update((value) => confirmScope(value, snapshot, "account", snapshot.account)); messages.push("Demo preferences updated for this visit.");
      } else if (!before.ready || before.conflict || before.needsReload) failures.push("Account preferences need a reload before saving.");
      else try {
        const response = await writePreferences(snapshot, { signal: controller.signal, csrfToken: authRef.current.csrfToken });
        if (!isCurrent()) return false;
        update((value) => ({ ...confirmScope(value, snapshot, "account", response.values), revision: response.revision, capabilities: response.capabilities }));
        messages.push("Account preferences saved.");
      } catch (error) {
        if (!isCurrent()) return false;
        sessionFailure(error);
        // An interrupted response can follow a committed write. Read the current
        // revision before offering another write; never blindly replay a PUT.
        if (!error?.status || error.status >= 500) {
          try {
            const confirmed = await readPreferences({ signal: controller.signal });
            if (!isCurrent()) return false;
            const recovered = recoverAccountSave(current.current, snapshot, confirmed);
            update(recovered.state);
            if (recovered.outcome === "confirmed") messages.push("Account preferences confirmed saved.");
            else failures.push(recovered.outcome === "conflict"
              ? "Account preferences changed elsewhere. Reload or review and reapply your retained draft before saving."
              : "Account preferences were not confirmed saved. Review the retained draft and retry.");
          } catch {
            if (isCurrent()) update((value) => ({ ...value, needsReload: true }));
            failures.push(errorCopy(error));
          }
        } else {
          update((value) => ({ ...value, conflict: error.status === 409, needsReload: error.status === 409 }));
          failures.push(errorCopy(error));
        }
      }
    }
    if (!isCurrent()) return false;
    if (targeted.device) {
      try {
        if (!deviceInfo.writable) throw new Error("incompatible");
        const confirmed = authRef.current.demoMode ? snapshot.device : saveDevicePreferences(owner, snapshot.device);
        update((value) => confirmScope(value, snapshot, "device", confirmed));
        messages.push(authRef.current.demoMode ? "Device demo preferences updated for this visit." : "Saved on this device.");
      } catch { failures.push("Device preferences could not be saved. Their draft is retained; check browser storage and retry."); }
    }
    if (!isCurrent()) return false;
    update((value) => ({ ...value, saving: false, undo: null, status: messages.join(" "), error: failures.join(" ") }));
    return failures.length === 0;
  }, [deviceInfo.writable, owner, update]);
  const persistDeviceValue = useCallback((key, value) => {
    if (current.current.saving || !authRef.current.demoMode && authRef.current.status !== "authenticated") return false;
    try {
      if (!deviceInfo.writable) throw new Error("incompatible");
      const next = validateValues({ ...current.current.saved.device, [key]: value }, "device");
      if (!authRef.current.demoMode) saveDevicePreferences(owner, next);
      update((currentState) => ({ ...currentState, saved: { ...currentState.saved, device: next },
        draft: { ...currentState.draft, device: { ...currentState.draft.device, [key]: value } } }));
      return true;
    } catch {
      update((currentState) => ({ ...currentState, error: "The device layout could not be remembered. The previous saved preference is unchanged." }));
      return false;
    }
  }, [deviceInfo.writable, owner, update]);
  const finishLeave = useCallback((proceed) => {
    const pending = leave.current; leave.current = null; setLeaveOpen(false);
    if (proceed) pending?.next(); pending?.resolve(proceed);
  }, []);
  const requestLeave = useCallback((next) => {
    if (!isDirty(current.current) && !current.current.saving) { next(); return Promise.resolve(true); }
    if (leave.current) return Promise.resolve(false);
    return new Promise((resolve) => { leave.current = { next, resolve }; setLeaveOpen(true); });
  }, []);
  useEffect(() => {
    registerGuard?.(previewEnabled ? requestLeave : null);
    return () => registerGuard?.(null);
  }, [previewEnabled, registerGuard, requestLeave]);
  useEffect(() => {
    const warn = (event) => { if (isDirty(current.current) || current.current.saving) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, []);
  const effective = previewEnabled ? state.draft : state.saved;
  return <Context.Provider value={{ ...state, dirty: isDirty(state), effective, change, cancel, save, reload, applyDraft, undoDraft,
    requestLeave, persistDeviceValue, deviceWarning: deviceInfo.warning, deviceWritable: deviceInfo.writable }}>
    {children}
    {leaveOpen && <PreferenceDialog title="Save your preference changes?" busy={state.saving} onClose={() => finishLeave(false)}>
      <p>Your conversation and unsent question will stay in the workspace.</p>
      {state.error && <p role="alert">{state.error}</p>}
      <div className="settings-dialog-actions"><button autoFocus type="button" disabled={state.saving} onClick={() => finishLeave(false)}>Keep editing</button>
        <button type="button" disabled={state.saving} onClick={() => { cancel(); finishLeave(true); }}>Discard changes</button>
        <button type="button" disabled={state.saving} onClick={async () => { if (await save()) finishLeave(true); }}>{state.saving ? "Saving…" : "Save and leave"}</button></div>
    </PreferenceDialog>}
  </Context.Provider>;
}
