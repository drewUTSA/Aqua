import React, { useEffect, useId, useReducer, useRef, useState } from "react";
import PreferenceDialog from "./PreferenceDialog.jsx";
import { usePreferences } from "./PreferencesProvider.jsx";
import { readAccount, saveAccountName, readAccountMethods, readAccountSessions, normalizeDisplayName } from "./accountClient.js";
import { acceptsAccountSnapshot, accountFailure, nameEditor, nameEditorReducer } from "./accountState.js";
import useAccountScope from "./useAccountScope.js";
import AccountSecurityDialog from "./AccountSecurityDialog.jsx";
import AccountIdentityDialog from "./AccountIdentityDialog.jsx";
import { canAccountAction } from "./accountSecurityState.js";
import { validId } from "../services/workspaceContract.js";
import { formatTimestamp } from "../services/preferenceFormatting.js";
import "../styles/account-foundation.css";

function NameEditor({ auth, profile, onConfirmed, onClose }) {
  const [state, dispatch] = useReducer(nameEditorReducer, profile, nameEditor), stateRef = useRef(state);
  stateRef.current = state;
  const scope = useAccountScope(auth), id = useId(), locked = useRef(false);
  const busy = ["saving", "checking"].includes(state.stage), editable = state.stage === "editing";
  const active = auth.status === "authenticated";
  useEffect(() => {
    if (active || !["saving", "checking"].includes(stateRef.current.stage)) return;
    locked.current = false;
    dispatch({ type: stateRef.current.stage === "saving" ? "failed" : "check-failed", error: { status: 0 } });
  }, [active]);
  const save = async (event) => {
    event.preventDefault();
    if (locked.current || stateRef.current.stage !== "editing" || !active) return;
    let name;
    try { name = normalizeDisplayName(stateRef.current.draft); }
    catch { dispatch({ type: "invalid" }); return; }
    const request = scope.begin("name");
    if (!request) return;
    locked.current = true;
    const base = stateRef.current.base;
    dispatch({ type: "save", name });
    try {
      const next = await saveAccountName(auth.user.id, { revision: base.revision, name }, { csrfToken: auth.csrfToken, signal: request.signal });
      if (!request.current()) return;
      dispatch({ type: "saved", profile: next });
      onConfirmed(next);
      onClose();
      // A same-owner refresh updates the account menu without resetting chats
      // or mixing the independent presentation draft into this mutation.
      void auth.refresh?.();
    } catch (error) {
      if (request.current()) { dispatch({ type: "failed", error }); if (error?.status === 401) void auth.refresh?.(); }
    } finally { locked.current = false; request.finish(); }
  };
  const reconcile = async () => {
    if (locked.current || !["blocked", "review"].includes(stateRef.current.stage) || !active) return;
    const request = scope.begin("name");
    if (!request) return;
    locked.current = true;
    dispatch({ type: "check" });
    try {
      const next = await readAccount(auth.user.id, { signal: request.signal });
      if (!request.current()) return;
      const checked = { type: "checked", profile: next }, outcome = nameEditorReducer(stateRef.current, checked);
      dispatch(checked);
      if (["complete", "review"].includes(outcome.stage)) onConfirmed(next, false);
    } catch (error) {
      if (request.current()) { dispatch({ type: "check-failed", error }); if (error?.status === 401) void auth.refresh?.(); }
    } finally { locked.current = false; request.finish(); }
  };
  return <PreferenceDialog title="Edit display name" onClose={onClose} busy={busy} className="account-name-dialog">
    <p>Your display name is saved to your account separately from appearance and other preferences.</p>
    <form onSubmit={save}>
      <label className="account-name-field" htmlFor={id}>Display name
        <input id={id} data-account-name-input autoFocus type="text" autoComplete="nickname" value={state.draft}
          maxLength={240} disabled={busy || state.stage === "complete" || !active}
          aria-describedby={`${id}-help${state.error ? ` ${id}-error` : ""}`} aria-invalid={Boolean(state.error) || undefined}
          onChange={(event) => dispatch({ type: "edit", value: event.target.value })} /></label>
      <p id={`${id}-help`} className="account-muted">1–120 characters. Your verified email and sign-in methods stay the same.</p>
      {state.error && <p id={`${id}-error`} className="settings-error" role="alert">{state.error}</p>}
      {state.stage === "blocked" && <button type="button" data-account-reconcile onClick={reconcile} disabled={!active}>
        {state.reason === "conflict" ? "Reload saved name" : "Check saved name"}</button>}
      {state.stage === "checking" && <p role="status">Checking the saved name…</p>}
      {state.stage === "review" && <div className="account-name-review"><p>The saved name is <strong>{state.latest.user.name || "Not set"}</strong>.</p>
        <p>Your entered name remains above. Choose which version to review before saving.</p>
        <div className="account-actions"><button type="button" data-account-keep-edit onClick={() => dispatch({ type: "keep-edit" })}>Keep my edit</button>
          <button type="button" onClick={() => dispatch({ type: "use-saved" })}>Use saved name</button></div></div>}
      {state.stage === "complete" && <p role="status">Your saved name is confirmed.</p>}
      <div className="settings-dialog-actions"><button type="button" onClick={() => {
        if (state.stage === "complete" || state.latest) void auth.refresh?.();
        onClose();
      }} disabled={busy}>{state.stage === "complete" ? "Done" : "Cancel"}</button>
        {state.stage !== "complete" && <button type="submit" className="opal-primary" data-account-save-name disabled={!editable || busy || !active}>
          {state.stage === "saving" ? "Saving name…" : "Save name"}</button>}</div>
    </form>
  </PreferenceDialog>;
}

export function AccountMethods({ data, onUnlink, canUnlink = () => false }) {
  return <><dl className="account-detail-list" data-account-methods>
    <div><dt>Password</dt><dd>{data.password.linked ? "Linked" : "Not linked"}
      <span className="account-muted">{data.password.available ? "Sign-in available" : "Sign-in currently unavailable"}</span></dd></div>
    <div><dt>Google</dt><dd>{data.google.linked ? `Linked · ${data.google.identities.length} ${data.google.identities.length === 1 ? "identity" : "identities"}` : "Not linked"}
      <span className="account-muted">{data.google.available ? "Sign-in available" : "Sign-in currently unavailable"}</span></dd></div>
  </dl>{data.google.identities.length>0&&<><ul className="account-identity-list">{data.google.identities.map((identity,index)=><li key={identity.id}><span>{identity.email||"Google account"}{data.google.identities.length>1?` · ${index+1}`:""}</span>{onUnlink&&<button type="button" data-account-unlink-google={index} disabled={!canUnlink(identity)} onClick={()=>onUnlink(identity)}>Remove this Google identity</button>}</li>)}</ul><p className="account-muted">Google addresses are provider-reported labels. They do not verify your AQUA primary mailbox.</p></>}</>;
}

export function AccountSessions({ data, preferences, onRevoke, canRevoke = () => false }) {
  const current = data.items.filter((item) => item.current), others = data.items.filter((item) => !item.current);
  const item = (session) => <li key={session.id} className="account-session">
    <div className="account-session-heading"><strong>{session.device_label}</strong>{session.current && <span className="account-current">This session</span>}
      {onRevoke && <button type="button" data-account-revoke-session={session.current ? "current" : "other"} disabled={!canRevoke(session)}
        onClick={() => onRevoke(session)}>{session.current ? "End this session" : "End this other session"}</button>}</div>
    <p>{session.method === "password" ? "Password" : session.method === "google" ? "Google" : "Sign-in"}</p>
    <dl><div><dt>Signed in</dt><dd><time dateTime={session.authenticated_at}>{formatTimestamp(session.authenticated_at, preferences)}</time></dd></div>
      <div><dt>Last active</dt><dd><time dateTime={session.last_activity_at}>{formatTimestamp(session.last_activity_at, preferences)}</time></dd></div>
      <div><dt>Idle expiry</dt><dd><time dateTime={session.idle_expires_at}>{formatTimestamp(session.idle_expires_at, preferences)}</time></dd></div>
      <div><dt>Session expiry</dt><dd><time dateTime={session.absolute_expires_at}>{formatTimestamp(session.absolute_expires_at, preferences)}</time></dd></div></dl>
  </li>;
  return <div data-account-sessions><h4>Current session</h4><ul className="account-session-list">{current.map(item)}</ul>
    <h4>Other active sessions</h4>{others.length ? <ul className="account-session-list">{others.map(item)}</ul> : <p>No other active sessions.</p>}
    <p className="account-muted">Up to 20 active sessions are shown when you request this list. It does not refresh automatically.</p></div>;
}

function OwnedAccount({ auth }) {
  const { effective } = usePreferences(), scope = useAccountScope(auth), owner = auth.user.id;
  const [profile, setProfile] = useState(null), profileRef = useRef(null);
  const [status, setStatus] = useState(""), [editing, setEditing] = useState(false);
  const [securityAction, setSecurityAction] = useState(null);
  const [resources, setResources] = useState({ profile: { busy: false, error: "" }, methods: { busy: false, error: "", data: null }, sessions: { busy: false, error: "", data: null } });
  const active = auth.status === "authenticated";
  const can = action => active && canAccountAction({ profile, methods: resources.methods.data, sessions: resources.sessions.data }, action);
  const startSecurity = action => { if (!editing && !securityAction && can(action)) setSecurityAction(action); };
  const update = (kind, next) => setResources((current) => ({ ...current, [kind]: { ...current[kind], ...next } }));
  const confirm = (next, saved = true) => {
    if (!acceptsAccountSnapshot(profileRef.current, next)) return;
    profileRef.current = next;
    setProfile(next);
    if (saved) setStatus("Display name saved.");
  };
  const load = async (kind) => {
    const request = scope.begin(kind);
    if (!request) return;
    update(kind, { busy: true, error: "" });
    try {
      const next = await (kind === "profile" ? readAccount(owner, { signal: request.signal })
        : kind === "methods" ? readAccountMethods({ signal: request.signal }) : readAccountSessions({ signal: request.signal }));
      if (!request.current()) return;
      if (kind === "profile") confirm(next, false);
      update(kind, { data: next, busy: false });
    } catch (error) {
      if (request.current()) { update(kind, { busy: false, error: accountFailure(error) }); if (error?.status === 401) void auth.refresh?.(); }
    } finally { request.finish(); }
  };
  useEffect(() => { if (active && !profileRef.current) void load("profile"); }, [active, owner]);
  useEffect(() => {
    if (!active) setResources((current) => Object.fromEntries(Object.entries(current).map(([key, value]) => [key, { ...value, busy: false }])));
  }, [active]);
  return <div className="account-foundation" data-account-foundation>
    <section className="account-section" aria-labelledby="account-profile-heading"><div className="account-section-heading"><h3 id="account-profile-heading">Profile</h3>
      {profile && <button type="button" data-account-edit-name disabled={!active || resources.profile.busy} onClick={() => { setStatus(""); setEditing(true); }}>Edit name</button>}</div>
      {resources.profile.busy && <p role="status">Loading account details…</p>}
      {resources.profile.error && <div className="settings-error" role="alert"><p>{resources.profile.error}</p><button type="button" disabled={!active || resources.profile.busy} onClick={() => load("profile")}>Retry account details</button></div>}
      {profile && <dl className="account-detail-list" data-account-profile><div><dt>Display name</dt><dd data-account-saved-name>{profile.user.name || "Not set"}</dd></div>
        <div><dt>Primary email</dt><dd><span data-account-primary-email>{profile.user.email}</span><span className="account-muted">Verified</span></dd></div></dl>}
      <p className="account-muted">Name changes save here. Preference Save, Cancel, import and reset do not change your account.</p>
      <div className="account-security-action"><button type="button" data-account-change-email disabled={!can({operation:"email_change"})} onClick={()=>startSecurity({operation:"email_change"})}>Change primary email</button><p className="account-muted">Requires fresh verification and confirmation from both the current and new mailbox.</p></div>
      {status && <p role="status">{status}</p>}
    </section>
    <section className="account-section" aria-labelledby="account-methods-heading"><div className="account-section-heading"><div><h3 id="account-methods-heading">Sign-in methods</h3>
      <p>Review which methods are linked and available.</p></div><button type="button" data-account-load-methods disabled={!active || resources.methods.busy} onClick={() => load("methods")}>
        {resources.methods.busy ? "Loading methods…" : resources.methods.data ? "Refresh methods" : "Review methods"}</button></div>
      {resources.methods.error && <p className="settings-error" role="alert">{resources.methods.error}</p>}
      {resources.methods.data && <AccountMethods data={resources.methods.data} canUnlink={identity=>can({operation:"google_unlink",identity})} onUnlink={identity=>startSecurity({operation:"google_unlink",identity})} />}
      <div className="account-security-action"><button type="button" data-account-change-password disabled={!can({ operation: "password_change" })}
        onClick={() => startSecurity({ operation: "password_change" })}>Change password</button>
        <p className="account-muted">{!resources.methods.data ? "Review your sign-in methods to check available password actions."
          : !resources.methods.data.password.linked ? "A first password requires an available linked Google identity and confirmation from your current primary mailbox."
            : !can({ operation: "password_change" }) ? "Password changes are currently unavailable. Your linked sign-in methods are shown above."
              : "Changing your password signs out every active session."}</p></div>
      {resources.methods.data?.password.linked===false&&<div className="account-security-action"><button type="button" data-account-add-password disabled={!can({operation:"password_add"})} onClick={()=>startSecurity({operation:"password_add"})}>Add a password</button></div>}
      <div className="account-security-action"><button type="button" data-account-link-google disabled={!can({operation:"google_link"})} onClick={()=>startSecurity({operation:"google_link"})}>Link a Google identity</button><p className="account-muted">Your existing method and the new Google identity are verified separately. Accounts are never merged.</p></div>
    </section>
    <section className="account-section" aria-labelledby="account-sessions-heading"><div className="account-section-heading"><div><h3 id="account-sessions-heading">Active sessions</h3>
      <p>Review your current session and other active sign-ins.</p></div><button type="button" data-account-load-sessions disabled={!active || resources.sessions.busy} onClick={() => load("sessions")}>
        {resources.sessions.busy ? "Loading sessions…" : resources.sessions.data ? "Refresh sessions" : "Review sessions"}</button></div>
      {resources.sessions.error && <p className="settings-error" role="alert">{resources.sessions.error}</p>}
      {resources.sessions.data && <><AccountSessions data={resources.sessions.data} preferences={effective.account}
        canRevoke={session => can({ operation: "session_revoke", session })} onRevoke={session => startSecurity({ operation: "session_revoke", session })} />
        <div className="account-security-action"><button type="button" data-account-revoke-all disabled={!can({ operation: "sessions_revoke_all" })}
          onClick={() => startSecurity({ operation: "sessions_revoke_all" })}>End all sessions</button>
          <p className="account-muted">Ending sessions requires an available linked sign-in method and fresh verification.</p></div></>}
    </section>
    <p className="account-future">Account security notices are required for supported identity changes and are separate from optional in-app success messages. Optional email subscriptions and browser notifications are unavailable. Current sign-out is in your account menu.</p>
    {editing && profile && <NameEditor auth={auth} profile={profile} onConfirmed={confirm} onClose={() => setEditing(false)} />}
    {securityAction&&["google_link","google_unlink","password_add","email_change"].includes(securityAction.operation)&&<AccountIdentityDialog auth={auth} action={securityAction} methods={resources.methods.data} allowed={can(securityAction)} onClose={()=>setSecurityAction(null)} onProfile={next=>confirm(next,false)} onMethods={data=>update("methods",{data,error:"",busy:false})}/>}
    {securityAction && !["google_link","google_unlink","password_add","email_change"].includes(securityAction.operation)&&<AccountSecurityDialog auth={auth} action={securityAction} methods={resources.methods.data} allowed={can(securityAction)} onClose={() => setSecurityAction(null)}
      onProfile={next => confirm(next, false)}
      onSessions={data => update("sessions", { data, error: "", busy: false })} onRevoked={id => {
        setResources(current => ({ ...current, sessions: { ...current.sessions, data: { ...current.sessions.data, items: current.sessions.data.items.filter(item => item.id !== id) } } }));
        setStatus("Session ended.");
      }} />}
  </div>;
}

export default function AccountFoundation({ auth }) {
  if (auth.demoMode || !validId(auth.user?.id)) return <aside className="settings-information"><h3>Account details</h3>
    <p>Account profile, sign-in methods and active sessions require a verified signed-in account.</p></aside>;
  return <OwnedAccount key={auth.user.id} auth={auth} />;
}
