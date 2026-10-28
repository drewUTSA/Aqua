import React, { useEffect, useId, useLayoutEffect, useReducer, useRef, useState } from "react";
import PreferenceDialog from "./PreferenceDialog.jsx";
import { usePreferences } from "./PreferencesProvider.jsx";
import { readAccount, saveAccountName, readAccountMethods, readAccountSessions, normalizeDisplayName } from "./accountClient.js";
import { acceptsAccountSnapshot, accountFailure, createAccountRequestScope, nameEditor, nameEditorReducer } from "./accountState.js";
import { validId } from "../services/workspaceContract.js";
import { formatTimestamp } from "../services/preferenceFormatting.js";
import "../styles/account-foundation.css";

function useAccountScope(auth) {
  const identity = useRef(null);
  identity.current = { owner: auth.user?.id, active: auth.status === "authenticated" && !auth.demoMode };
  const scope = useRef(null);
  if (!scope.current) scope.current = createAccountRequestScope(auth.user.id, () => identity.current);
  useLayoutEffect(() => { scope.current.activate(); return () => scope.current.dispose(); }, []);
  useLayoutEffect(() => { if (!identity.current.active) scope.current.abort(); }, [auth.status, auth.demoMode]);
  return scope.current;
}

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

export function AccountMethods({ data }) {
  return <dl className="account-detail-list" data-account-methods>
    <div><dt>Password</dt><dd>{data.password.linked ? "Linked" : "Not linked"}
      <span className="account-muted">{data.password.available ? "Sign-in available" : "Sign-in currently unavailable"}</span></dd></div>
    <div><dt>Google</dt><dd>{data.google.linked ? `Linked · ${data.google.identities.length} ${data.google.identities.length === 1 ? "identity" : "identities"}` : "Not linked"}
      <span className="account-muted">{data.google.available ? "Sign-in available" : "Sign-in currently unavailable"}</span></dd></div>
  </dl>;
}

export function AccountSessions({ data, preferences }) {
  const current = data.items.filter((item) => item.current), others = data.items.filter((item) => !item.current);
  const item = (session) => <li key={session.id} className="account-session">
    <div className="account-session-heading"><strong>{session.device_label}</strong>{session.current && <span className="account-current">This session</span>}</div>
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
  const [resources, setResources] = useState({ profile: { busy: false, error: "" }, methods: { busy: false, error: "", data: null }, sessions: { busy: false, error: "", data: null } });
  const active = auth.status === "authenticated";
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
      {status && <p role="status">{status}</p>}
    </section>
    <section className="account-section" aria-labelledby="account-methods-heading"><div className="account-section-heading"><div><h3 id="account-methods-heading">Sign-in methods</h3>
      <p>Review which methods are linked and available.</p></div><button type="button" data-account-load-methods disabled={!active || resources.methods.busy} onClick={() => load("methods")}>
        {resources.methods.busy ? "Loading methods…" : resources.methods.data ? "Refresh methods" : "Review methods"}</button></div>
      {resources.methods.error && <p className="settings-error" role="alert">{resources.methods.error}</p>}
      {resources.methods.data && <AccountMethods data={resources.methods.data} />}
    </section>
    <section className="account-section" aria-labelledby="account-sessions-heading"><div className="account-section-heading"><div><h3 id="account-sessions-heading">Active sessions</h3>
      <p>Review your current session and other active sign-ins.</p></div><button type="button" data-account-load-sessions disabled={!active || resources.sessions.busy} onClick={() => load("sessions")}>
        {resources.sessions.busy ? "Loading sessions…" : resources.sessions.data ? "Refresh sessions" : "Review sessions"}</button></div>
      {resources.sessions.error && <p className="settings-error" role="alert">{resources.sessions.error}</p>}
      {resources.sessions.data && <AccountSessions data={resources.sessions.data} preferences={effective.account} />}
    </section>
    <p className="account-future">Email and password changes, linking or removing methods, additional verification and session revocation are not available yet. Current sign-out is in your account menu.</p>
    {editing && profile && <NameEditor auth={auth} profile={profile} onConfirmed={confirm} onClose={() => setEditing(false)} />}
  </div>;
}

export default function AccountFoundation({ auth }) {
  if (auth.demoMode || !validId(auth.user?.id)) return <aside className="settings-information"><h3>Account details</h3>
    <p>Account profile, sign-in methods and active sessions require a verified signed-in account.</p></aside>;
  return <OwnedAccount key={auth.user.id} auth={auth} />;
}
