import React, { useEffect, useId, useLayoutEffect, useReducer, useRef } from "react";
import PreferenceDialog from "./PreferenceDialog.jsx";
import AccountProofStep from "./AccountProofStep.jsx";
import useAccountScope from "./useAccountScope.js";
import { changeAccountPassword, revokeAccountSession, revokeAllAccountSessions } from "./accountSecurityClient.js";
import { readAccount, readAccountSessions } from "./accountClient.js";
import { createActionProofVault, securityActionReducer, securityActionState } from "./accountSecurityState.js";
import { validateNewPassword } from "../components/auth/authFormPolicy.js";

const titles = { password_change: "Change password", session_revoke: "End session", sessions_revoke_all: "End all sessions" };
export default function AccountSecurityDialog({ auth, action, methods, allowed, onClose, onProfile, onSessions, onRevoked }) {
  const [state, dispatch] = useReducer(securityActionReducer, undefined, securityActionState), stateRef = useRef(state);
  stateRef.current = state;
  // Uncontrolled password fields keep live values out of React state and HTML
  // value attributes. Read them only for the user's explicit submission.
  const newPassword = useRef(null), confirmation = useRef(null);
  const scope = useAccountScope(auth), identity = useRef(null), vault = useRef(null), locked = useRef(false), cancel = useRef(null), authority = useRef(auth.csrfToken), id = useId();
  const authorityActive = auth.status === "authenticated", active = authorityActive && allowed;
  identity.current = { owner: auth.user.id, csrfToken: auth.csrfToken, active };
  if (!vault.current) vault.current = createActionProofVault(auth.user.id, action, () => identity.current);
  const clearFields = () => { for (const ref of [newPassword, confirmation]) if (ref.current) { ref.current.value = ""; ref.current.defaultValue = ""; } };
  const clearSecrets = () => { vault.current.clear(); clearFields(); };
  const target = action.operation === "session_revoke" ? { operation: action.operation, target_session_id: action.session.id } : { operation: action.operation };
  const busy = ["verifying", "mutating", "checking"].includes(state.phase);
  const close = () => {
    if (stateRef.current.phase === "mutating") return;
    scope.abort(); locked.current = false; clearSecrets(); onClose();
  };
  useLayoutEffect(() => () => { vault.current.clear(); clearFields(); }, []);
  useLayoutEffect(() => {
    const changed = authority.current !== auth.csrfToken;
    authority.current = auth.csrfToken;
    if (active && !changed) return;
    scope.abort(); locked.current = false; clearSecrets(); dispatch({ type: "interrupted", preserveReview: authorityActive && !changed });
  }, [active, auth.csrfToken]);
  useLayoutEffect(() => { if (["verify", "confirm", "review"].includes(state.phase) && cancel.current?.closest("dialog[open]")) cancel.current.focus({ preventScroll: true }); }, [state.phase]);
  useEffect(() => {
    if (state.phase !== "confirm") return undefined;
    const timer = setTimeout(() => { clearSecrets(); dispatch({ type: "expired" }); }, Math.max(0, vault.current.deadline() - Date.now()));
    return () => clearTimeout(timer);
  }, [state.phase]);

  const commit = async event => {
    event.preventDefault();
    if (locked.current || stateRef.current.phase !== "confirm" || !active) return;
    const enteredNewPassword = newPassword.current?.value || "", repeatedPassword = confirmation.current?.value || "";
    if (action.operation === "password_change" && validateNewPassword(enteredNewPassword, repeatedPassword)) { dispatch({ type: "validation" }); return; }
    const proof = vault.current.take(action);
    if (!proof) { clearSecrets(); dispatch({ type: "expired" }); return; }
    const request = scope.begin("security");
    if (!request) { clearSecrets(); dispatch({ type: "interrupted" }); return; }
    clearSecrets(); locked.current = true; dispatch({ type: "mutate" });
    try {
      const options = { csrfToken: auth.csrfToken, signal: request.signal };
      const result = action.operation === "password_change" ? await changeAccountPassword(proof, enteredNewPassword, options)
        : action.operation === "sessions_revoke_all" ? await revokeAllAccountSessions(proof, options)
          : await revokeAccountSession(action.session.id, proof, action.session.current, options);
      if (!request.current()) return;
      dispatch({ type: "confirmed" });
      if (result.current_session_revoked) {
        clearSecrets(); onClose();
        // Only a closed, confirmed commit response may clear cached authority.
        if (auth.sessionEnded) auth.sessionEnded(); else void auth.refresh?.();
      } else onRevoked(action.session.id);
    } catch (error) {
      if (request.current()) { clearSecrets(); dispatch({ type: "mutation-failed", error }); if (error?.status === 401) void auth.refresh?.(); }
    } finally { locked.current = false; request.finish(); }
  };

  const reconcile = async () => {
    if (locked.current || stateRef.current.phase !== "uncertain" || !authorityActive) return;
    const request = scope.begin("security");
    if (!request) return;
    clearSecrets(); locked.current = true; dispatch({ type: "check" });
    try {
      // A 401 may mean this or another action ended authority. It cannot prove
      // which mutation happened and never becomes a success acknowledgement.
      const profile = await readAccount(auth.user.id, { signal: request.signal });
      if (!request.current()) return;
      let absent = false, snapshot = null;
      if (action.operation !== "password_change") {
        const sessions = await readAccountSessions({ signal: request.signal });
        if (!request.current()) return;
        absent = action.operation === "session_revoke" && !sessions.items.some(item => item.id === action.session.id);
        snapshot = sessions;
      }
      dispatch({ type: "checked", targetAbsent: absent });
      onProfile?.(profile);
      if (snapshot) onSessions(snapshot);
    } catch (error) {
      if (request.current()) { dispatch({ type: "check-failed" }); if (error?.status === 401) void auth.refresh?.(); }
    } finally { locked.current = false; request.finish(); }
  };

  const submitText = action.operation === "password_change" ? "Change password and sign out" : action.operation === "sessions_revoke_all" ? "End all sessions" : action.session.current ? "End this session" : "End this other session";
  return <PreferenceDialog title={titles[action.operation]} onClose={close} busy={state.phase === "mutating"} className="account-security-dialog" initialFocusRef={cancel}>
    <div data-account-security-phase={state.phase}>
      <p>{action.operation === "password_change" ? "Changing your password signs out every active session, including this one. You will need to sign in again."
        : action.operation === "sessions_revoke_all" ? "This ends every active session, including this one. You will need to sign in again."
          : action.session.current ? "This ends your current session. You will need to sign in again." : "This ends the selected session. Your current session will stay signed in."}</p>
      {action.operation === "session_revoke" && <p><strong>{action.session.device_label}</strong>{action.session.current ? " · This session" : " · Other session"}</p>}
      {state.error && <p className="settings-error" role="alert">{state.error}</p>}
      {["verify", "verifying"].includes(state.phase) && <AccountProofStep auth={auth} target={target} methods={methods} allowed={active} phase={state.phase} cancelRef={cancel} onClose={close}
        onStart={() => dispatch({ type: "verify" })} onProof={proof => { if (!vault.current.store(proof)) throw Error("verification_unavailable"); dispatch({ type: "verified" }); }}
        onFailure={error => { vault.current.clear(); dispatch({ type: "verification-failed", error }); }} />}
      {state.phase === "confirm" && <form onSubmit={commit}>
        <p role="status">Sign-in method verified for this action. Review before confirming.</p>
        {action.operation === "password_change" && <><label className="account-security-field" htmlFor={`${id}-new`}>New password<input ref={newPassword} id={`${id}-new`} data-account-new-password type="password"
          autoComplete="new-password" autoCapitalize="none" spellCheck={false} required maxLength={1024} disabled={!active} /></label>
          <label className="account-security-field" htmlFor={`${id}-confirm`}>Confirm new password<input ref={confirmation} id={`${id}-confirm`} data-account-confirm-password type="password"
            autoComplete="new-password" autoCapitalize="none" spellCheck={false} required maxLength={1024} disabled={!active} /></label>
          <p className="account-muted">Use 15–128 characters. Common or compromised passwords are not accepted. Passwords are never truncated.</p></>}
        <div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button>
          <button type="submit" data-account-confirm-security disabled={!active}>{submitText}</button></div>
      </form>}
      {state.phase === "mutating" && <p role="status">Confirming the security change…</p>}
      {state.phase === "uncertain" && <div className="settings-dialog-actions"><button type="button" onClick={close}>Close</button>
        <button type="button" data-account-check-security disabled={!authorityActive} onClick={reconcile}>Check current access</button></div>}
      {state.phase === "checking" && <><p role="status">Checking current access…</p><button type="button" onClick={close}>Close</button></>}
      {state.phase === "review" && <><p role="status">{state.check === "absent" ? "The selected session is no longer listed as active. This does not confirm which action ended it."
        : "Your current sign-in is still active. The earlier change is unconfirmed. Review before starting a new verification."}</p>
        <div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Close</button>
          {state.check === "active" && <button type="button" data-account-restart-security disabled={!active} onClick={() => dispatch({ type: "restart" })}>Start a new verification</button>}</div></>}
      {state.phase === "done" && <><p role="status">The selected session has ended.</p><div className="settings-dialog-actions"><button type="button" onClick={close}>Done</button></div></>}
      {!allowed && state.phase !== "done" && !(state.phase === "review" && state.check === "absent") && <p className="account-muted">This security action is currently unavailable. Review your sign-in methods and active sessions before trying again.</p>}
    </div>
  </PreferenceDialog>;
}
