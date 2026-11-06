import React, { createContext, lazy, Suspense, useContext, useEffect, useLayoutEffect, useReducer, useRef, useState } from "react";
import PreferenceDialog from "./PreferenceDialog.jsx";
import { DELETION_SCOPES } from "./dataDeletionContract.js";
import { createDeletionReceipt, deletionReducer, initialDeletion } from "./dataDeletionState.js";
import { assertHistory, captureHistory } from "../services/historyAuthority.js";

const Context = createContext(null);
const DataDeletionContent = lazy(() => import("./DataDeletionContent.jsx"));
class DeletionViewBoundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? this.props.fallback : this.props.children; }
}
export const useDataDeletion = () => useContext(Context);
const proofAvailable = methods => methods?.capabilities?.recent_proof === true && (methods.password?.linked === true && methods.password.available === true || methods.google?.available === true && methods.google.identities.length > 0);
export default function DataDeletionProvider({ auth, children }) {
  const [entry, setEntry] = useState(null), [state, dispatch] = useReducer(deletionReducer, undefined, initialDeletion);
  const [privateEpoch, setPrivateEpoch] = useState(0), [privateBlocked, setPrivateBlocked] = useState(false);
  const receipt = useRef(null), vault = useRef(null), client = useRef(null), identity = useRef(null), active = useRef(null), generation = useRef(0), stateRef = useRef(state), authRef = useRef(auth), cancel = useRef(null), confirmation = useRef(null), locked = useRef(false);
  stateRef.current = state; authRef.current = auth;
  const currentReceipt = receipt.current;
  let historyCurrent = false;
  try { if (currentReceipt) { assertHistory(currentReceipt.history); historyCurrent = true; } } catch { /* Old private authority stays locked. */ }
  identity.current = { owner: auth.user?.id, csrfToken: auth.csrfToken, active: auth.status === "authenticated" && historyCurrent, generation: currentReceipt?.history.sequence };
  const reset = () => {
    generation.current++; active.current?.abort(); active.current = null;
    receipt.current?.clear(); receipt.current = null; vault.current?.clear(); vault.current = null; client.current = null;
    if (confirmation.current) confirmation.current.value = "";
    locked.current = false; setEntry(null); dispatch({ type: "reset" }); setPrivateBlocked(false);
  };
  useLayoutEffect(() => {
    const value = receipt.current;
    if (!value) return;
    if (auth.status === "signingin" || !value.matches(auth) || !value.attempted() && !historyCurrent) { reset(); return; }
    if (!value.attempted() && auth.status !== "authenticated") { vault.current?.clear(); dispatch({ type: "verification-failed" }); }
    if (value.scope === "chat_history_v1" && value.attempted() && auth.status === "authenticated") {
      const current = captureHistory();
      if (current.owner === value.owner && current.csrf === value.csrf && current.revision && current.revision !== value.history.revision) setPrivateBlocked(false);
    }
  }, [auth.status, auth.user?.id, auth.csrfToken, auth.historyEpoch, historyCurrent]);
  useEffect(() => {
    if (!entry || !receipt.current) return undefined;
    const value = receipt.current;
    const timer = setTimeout(() => {
      if (receipt.current !== value) return;
      generation.current++; active.current?.abort(); value.clear(); receipt.current = null; vault.current?.clear(); vault.current = null; client.current = null;
      locked.current = false; setEntry(previous => previous ? { scope: previous.scope, methods: null, expired: true } : null);
      dispatch({ type: "expired" }); setPrivateBlocked(false);
    }, Math.max(0, value.deadline() - Date.now()));
    return () => clearTimeout(timer);
  }, [entry, state.job?.receipt_expires_at]);
  useEffect(() => () => { generation.current++; active.current?.abort(); receipt.current?.clear(); vault.current?.clear(); }, []);
  useEffect(() => {
    if (state.phase !== "confirm") return undefined;
    const timer = setTimeout(() => { vault.current?.clear(); if (confirmation.current) confirmation.current.value = ""; dispatch({ type: "verification-failed" }); }, Math.max(0, (vault.current?.deadline() || 0) - Date.now()));
    return () => clearTimeout(timer);
  }, [state.phase]);
  const open = async scope => {
    if (receipt.current || authRef.current.status !== "authenticated" || authRef.current.demoMode) return;
    const value = createDeletionReceipt(authRef.current.user.id, authRef.current.csrfToken, scope);
    receipt.current = value; const ticket = ++generation.current;
    const controller = new AbortController(); active.current = controller;
    const action = { operation: DELETION_SCOPES[scope].operation, intentId: value.intent };
    setEntry({ scope, methods: null, loading: true }); dispatch({ type: "reset" });
    try {
      const [{ readAccountMethods }, { createActionProofVault }, transport] = await Promise.all([import("./accountClient.js"), import("./accountSecurityState.js"), import("./dataDeletionClient.js")]);
      assertHistory(value.history);
      if (generation.current !== ticket || !value.matches(authRef.current)) return;
      client.current = transport;
      vault.current = createActionProofVault(value.owner, action, () => identity.current);
      const methods = await readAccountMethods({ signal: controller.signal, historyContext: value.history });
      assertHistory(value.history);
      if (generation.current !== ticket || !value.matches(authRef.current)) return;
      setEntry({ scope, methods, loading: false, unavailable: !proofAvailable(methods) });
    } catch (error) {
      if (generation.current === ticket) setEntry({ scope, methods: null, loading: false, unavailable: true });
    } finally { if (active.current === controller) active.current = null; }
  };
  const accept = (value, reply) => {
    if (receipt.current !== value || !value.matches(authRef.current)) return;
    dispatch({ type: "reply", job: reply.job });
    if (value.scope === "chat_history_v1") {
      value.applyHistoryRevision(reply.history_revision);
    }
  };
  const submit = async event => {
    event.preventDefault(); const value = receipt.current, transport = client.current;
    if (!value || !transport || locked.current || stateRef.current.phase !== "confirm" || !identity.current.active || confirmation.current?.value !== DELETION_SCOPES[value.scope].confirmation) return;
    const action = { operation: DELETION_SCOPES[value.scope].operation, intentId: value.intent }, proof = vault.current.take(action);
    if (!proof) { dispatch({ type: "verification-failed" }); return; }
    try { assertHistory(value.history); } catch { reset(); return; }
    if (!value.attempt()) return;
    confirmation.current.value = ""; locked.current = true; dispatch({ type: "submit" });
    const ticket = generation.current, controller = new AbortController(); active.current = controller;
    // Fetch starts with the captured authority before local account access is
    // ended. Only this receipt's metadata survives the private subtree removal.
    const pending = transport.startDataDeletion(value, proof, { signal: controller.signal });
    // Only scope and the purpose receipt survive an attempted deletion. Linked
    // method/email snapshots belong to ordinary authenticated account access.
    setEntry(previous => previous ? { scope: previous.scope, methods: null } : null);
    setPrivateEpoch(previous => previous + 1); setPrivateBlocked(true);
    if (value.scope === "account_v1") authRef.current.sessionEnded?.();
    else void authRef.current.refresh?.();
    try { const reply = await pending; if (generation.current === ticket) accept(value, reply); }
    catch { if (generation.current === ticket && value.current()) dispatch({ type: "uncertain" }); }
    finally { locked.current = false; if (active.current === controller) active.current = null; }
  };
  const check = async () => {
    const value = receipt.current, transport = client.current;
    if (!value || !transport || !value.current() || locked.current || !["uncertain", "observing"].includes(stateRef.current.phase)) return;
    locked.current = true; dispatch({ type: "check" }); const ticket = generation.current;
    const controller = new AbortController(); active.current = controller;
    try { const reply = await transport.reconcileDataDeletion(value, { signal: controller.signal }); if (generation.current === ticket) accept(value, reply); }
    catch { if (generation.current === ticket && value.current()) dispatch({ type: "uncertain" }); }
    finally { locked.current = false; if (active.current === controller) active.current = null; }
  };
  const close = () => { if (stateRef.current.phase === "submitting") return; reset(); };
  const verified = proof => {
    try { assertHistory(receipt.current?.history); } catch { reset(); return; }
    if (vault.current?.store(proof)) dispatch({ type: "verified" }); else dispatch({ type: "verification-failed" });
  };
  const scope = entry?.scope, info = scope && DELETION_SCOPES[scope];
  return <Context.Provider value={{ open, busy: entry !== null }}>
    {typeof children === "function" ? children({ privateEpoch, privateBlocked }) : children}
    {entry && <PreferenceDialog title={info.title} onClose={close} busy={state.phase === "submitting"} className="account-security-dialog" initialFocusRef={cancel}>
      <DeletionViewBoundary fallback={<><p role="alert">The deletion review is unavailable. Closing it does not confirm deletion.</p><button ref={cancel} autoFocus type="button" disabled={state.phase === "submitting"} onClick={close}>Close</button></>}><Suspense fallback={<><p role="status">Opening deletion review…</p><div className="settings-dialog-actions"><button ref={cancel} autoFocus type="button" onClick={close}>Cancel</button></div></>}><DataDeletionContent auth={auth} entry={entry} state={state} receipt={currentReceipt} allowed={identity.current.active} cancel={cancel} confirmation={confirmation} close={close} submit={submit} check={check} verified={verified} onVerify={() => dispatch({ type: "verify" })} onStart={() => dispatch({ type: "verifying" })} onFailure={() => { vault.current?.clear(); dispatch({ type: "verification-failed" }); }} /></Suspense></DeletionViewBoundary>
    </PreferenceDialog>}
  </Context.Provider>;
}
