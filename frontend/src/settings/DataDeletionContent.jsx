import React, { useLayoutEffect } from "react";
import AccountProofStep from "./AccountProofStep.jsx";
import { DELETION_SCOPES } from "./dataDeletionContract.js";

// Loaded only for an explicit deletion review. The parent keeps the receipt,
// private workspace fence and cancellation state across this presentation.
export default function DataDeletionContent({ auth, entry, state, receipt, allowed, cancel, confirmation, close, submit, check, verified, onVerify, onStart, onFailure }) {
  const scope = entry.scope, info = DELETION_SCOPES[scope], job = state.job;
  useLayoutEffect(() => {
    const button = cancel.current;
    if (button?.closest("dialog")?.open && !button.disabled) button.focus({ preventScroll: true });
  }, []);
  return (
      <div data-deletion-phase={state.phase}>
        {state.error && <p role="alert" className="settings-error">{state.error}</p>}
        {state.phase === "review" && <>
          <p>{scope === "account_v1" ? "Permanently close this AQUA account and remove its saved personal data. This page clears private workspace access when you send the request. If the outcome is unconfirmed, check this receipt before making another request." : "Permanently delete saved chats, messages and analysis results. Your account, projects and saved prompts remain available. Unsaved drafts in this visit will be cleared."}</p>
          <p>Deletion cannot be undone. Acceptance starts removal; it does not mean physical cleanup has finished. Encrypted backups, including legacy copies, may remain beyond 30 days while pruning is disabled. Restored copies apply retained deletion records before access resumes.</p>
          {entry.loading && <p role="status">Checking available verification methods…</p>}
          {entry.unavailable && <p role="status">A linked sign-in method is unavailable for verification. Close this review and try again when available.</p>}
          <div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="button" disabled={!allowed || entry.loading || entry.unavailable} onClick={() => onVerify()}>Continue to verification</button></div>
        </>}
        {["verify", "verifying"].includes(state.phase) && receipt && <AccountProofStep auth={auth} target={{ operation: info.operation, target_intent_id: receipt.intent }} methods={entry.methods} allowed={allowed} historyContext={receipt.history} phase={state.phase} cancelRef={cancel} onClose={close} onStart={() => onStart()} onProof={verified} onFailure={onFailure} />}
        {state.phase === "confirm" && <form onSubmit={submit}><p>Type <strong>{info.confirmation}</strong> to confirm this exact action.</p><label className="account-security-field">Confirmation<input ref={confirmation} autoComplete="off" spellCheck={false} autoCapitalize="none" required pattern={info.confirmation} maxLength={32} disabled={!allowed} /></label><div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Cancel</button><button type="submit" data-submit-private-deletion disabled={!allowed}>{info.title}</button></div></form>}
        {state.phase === "submitting" && <p role="status">Requesting deletion. Acceptance has not been confirmed yet…</p>}
        {state.phase === "checking" && <p role="status">Checking this exact deletion receipt…</p>}
        {job && <p role="status" data-deletion-state={job.state}>{({ awaiting_authority: "The deletion request is recorded, but independent acceptance is still unconfirmed. Physical cleanup is not complete.", accepted: "Deletion accepted. Physical cleanup has not finished.", purging: "Deletion accepted. Physical cleanup is in progress.", complete: "Deletion accepted and cleanup of the requested saved content is complete. Limited security and deletion metadata may remain. Encrypted backups may remain beyond 30 days while pruning is disabled. Restored copies apply retained deletion records before access resumes." })[job.state]}</p>}
        {["uncertain", "checking", "observing"].includes(state.phase) && <p>This page can check only this request's minimal status for up to ten minutes. Closing it, signing in again or expiry clears the receipt. A missing or expired receipt never confirms completion.</p>}
        {["uncertain", "observing"].includes(state.phase) && <div className="settings-dialog-actions"><button ref={cancel} type="button" onClick={close}>Close receipt</button>{job?.cleanup_complete !== true && <button type="button" data-check-deletion-receipt onClick={check}>Check deletion status</button>}</div>}
        {state.phase === "expired" && <button ref={cancel} type="button" onClick={close}>Close</button>}
      </div>
  );
}
