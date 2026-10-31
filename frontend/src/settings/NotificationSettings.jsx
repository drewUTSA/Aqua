import React, { useEffect, useId, useLayoutEffect, useReducer, useRef } from "react";
import { validId } from "../services/workspaceContract.js";
import useAccountScope from "./useAccountScope.js";
import { readNotificationSettings, saveNotificationSettings } from "./accountIdentityClient.js";
import { notificationEditor, notificationReducer, sameNotificationValues } from "./notificationState.js";

function OwnedNotifications({ auth, onConfirmed }) {
  const [state, dispatch] = useReducer(notificationReducer, undefined, notificationEditor), ref = useRef(state), locked = useRef(false), authority = useRef(auth.csrfToken),scope = useAccountScope(auth), id = useId();
  ref.current = state;
  const active = auth.status === "authenticated", editable = state.phase === "editing", busy = ["loading", "saving", "checking"].includes(state.phase);
  const load = async (checking = false) => {
    const request = scope.begin("notifications"); if (!request) return;
    if (checking) dispatch({ type: "check" });
    try { const snapshot = await readNotificationSettings(auth.user.id, { signal: request.signal }); if (!request.current()) return; dispatch({ type: checking ? "checked" : "loaded", snapshot }); onConfirmed?.(snapshot,{owner:auth.user.id,csrfToken:auth.csrfToken}); }
    catch (error) { if (request.current()) { dispatch({ type: checking ? "check-failed" : "load-failed" }); if (error?.status === 401) void auth.refresh?.(); } }
    finally { request.finish(); }
  };
  useEffect(() => { if (active && !ref.current.base) void load(); }, [active, auth.csrfToken]);
  useLayoutEffect(() => { const changed=authority.current!==auth.csrfToken;authority.current=auth.csrfToken;if (!active||changed) { scope.abort();locked.current = false; dispatch({ type: "interrupted" }); } }, [active, auth.csrfToken]);
  const save = async event => {
    event.preventDefault(); if (!active || !editable || locked.current) return;
    const request = scope.begin("notifications"); if (!request) return;
    const current = ref.current; locked.current = true; dispatch({ type: "save" });
    try { const snapshot = await saveNotificationSettings(auth.user.id, { expectedRevision: current.base.revision, ...current.draft }, { signal: request.signal, csrfToken: auth.csrfToken }); if (!request.current()) return; dispatch({ type: "saved", snapshot }); onConfirmed?.(snapshot,{owner:auth.user.id,csrfToken:auth.csrfToken}); }
    catch (error) { if (request.current()) { dispatch({ type: "failed", error }); if (error?.status === 401) void auth.refresh?.(); } }
    finally { locked.current = false; request.finish(); }
  };
  return <div className="notification-settings" data-notification-settings>
    <p>Choose optional generic success messages inside AQUA. Errors, session expiry and essential save feedback remain available.</p>
    <p>These choices save separately from presentation preferences. Import, reset and presentation Save do not subscribe you.</p>
    {state.phase === "loading" && <p role="status">Loading saved notification settings…</p>}
    {state.error && <p className="settings-error" role="alert">{state.error}</p>}
    {state.status && <p role="status">{state.status}</p>}
    {state.base && <form onSubmit={save}>
      <label className="notification-option"><input type="checkbox" data-notification-consent checked={state.draft.in_app_success} disabled={!active || !editable} onChange={event => dispatch({ type: "edit", key: "in_app_success", value: event.target.checked })} /> Show optional in-app success messages</label>
      <label className="notification-preview" htmlFor={id}>Success-message preview<select id={id} data-notification-preview value={state.draft.preview} disabled={!active || !editable} onChange={event => dispatch({ type: "edit", key: "preview", value: event.target.value })}><option value="generic">Generic message</option><option value="hidden">Hidden</option></select></label>
      <p className="account-muted">Generic messages contain no titles, questions, answers or result values. Hidden previews suppress these optional messages.</p>
      <div className="settings-dialog-actions"><button type="button" disabled={!active || !editable} onClick={() => dispatch({ type: "cancel" })}>Cancel notification edits</button>
        <button type="submit" data-save-notifications disabled={!active || !editable || sameNotificationValues(state.base.values, state.draft)}>{state.phase === "saving" ? "Saving…" : "Save notification settings"}</button></div>
    </form>}
    {["blocked", "unavailable"].includes(state.phase) && <button type="button" data-check-notifications disabled={!active || busy} onClick={() => load(true)}>Check saved notification settings</button>}
    {state.phase === "checking" && <p role="status">Checking saved settings…</p>}
    {state.phase === "review" && <div><p>Your saved choices changed. Review your selection before saving again.</p><div className="settings-dialog-actions"><button type="button" data-keep-notifications onClick={() => dispatch({ type: "keep" })}>Keep my selection</button><button type="button" onClick={() => dispatch({ type: "use-saved" })}>Use saved choices</button></div></div>}
    <p className="account-muted">Browser notifications, optional email, sounds and quiet hours are unavailable. AQUA does not request browser notification permission.</p>
  </div>;
}
export default function NotificationSettings({ auth, onConfirmed }) {
  return auth && !auth.demoMode && validId(auth.user?.id) ? <OwnedNotifications key={auth.user.id} auth={auth} onConfirmed={onConfirmed} /> : <p>Sign in to review notification settings.</p>;
}
