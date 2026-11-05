import { accountOwner } from "./accountContract.js";
import { actionEmail } from "./accountSecurityContract.js";
const OPERATIONS = new Set(["password_change", "password_add", "email_change", "google_link", "google_unlink", "session_revoke", "sessions_revoke_all", "data_export"]);
export function actionKey(action) {
  if (!action || !OPERATIONS.has(action.operation)) throw Error("account_action_invalid");
  const target = action.operation === "session_revoke" ? accountOwner(action.session?.id) : action.operation === "google_unlink" ? accountOwner(action.identity?.id)
    : action.operation === "email_change" ? actionEmail(action.email) : action.operation === "data_export" ? accountOwner(action.intentId) : "";
  return action.operation + ":" + target;
}

export function canAccountAction({ profile, methods, sessions }, action) {
  const password = methods?.password?.linked === true && methods.password.available === true, google = methods?.google?.available === true && methods.google.identities?.length > 0;
  if (!action || action.operation==='data_export' || !OPERATIONS.has(action.operation) || !password && !google) return false;
  for (const caps of [profile?.capabilities, methods.capabilities]) {
    if (caps?.recent_proof !== true || caps?.[action.operation] !== true) return false;
  }
  if (action.operation === "password_change") return password;
  if (action.operation === "password_add") return methods.password.linked === false && google;
  if (action.operation === "google_unlink") return methods.google.identities.some(item => item.id === action.identity?.id);
  if (["email_change", "google_link"].includes(action.operation)) return true;
  if (action.operation === "sessions_revoke_all") return sessions?.capabilities?.revoke_all === true && sessions.items.some(item => item.current);
  return sessions?.capabilities?.revoke_one === true && sessions.items.some(item => item.id === action.session?.id && item.current === action.session.current);
}

// The reducer holds no passwords, challenges or proofs. Those are short-lived
// request locals or the private vault below, never preference/device state.
export const securityActionState = () => ({ phase: "verify", error: "", check: "" });
export function securityFailure(error, phase) {
  if (error?.status === 429) return "Too many security actions. Wait before starting a fresh verification.";
  if (error?.status === 401) return "Your current sign-in could not be confirmed. Check your sign-in again.";
  if (error?.status === 403) return "This verification is invalid, expired or unavailable. Start a fresh verification.";
  if (error?.status === 404) return "This session is no longer available. Refresh the active session list.";
  if (error?.status === 422) return phase === "mutation" ? "Check the action details and any new password requirements, then verify again." : "The password could not be verified. Start a fresh verification.";
  return phase === "mutation" ? "AQUA could not confirm whether this change finished. Check current access before any new attempt."
    : "Verification could not be completed. Start a fresh verification when your connection is available.";
}

export function securityActionReducer(state, event) {
  switch (event.type) {
    case "verify": return state.phase === "verify" ? { phase: "verifying", error: "", check: "" } : state;
    case "verified": return state.phase === "verifying" ? { phase: "confirm", error: "", check: "" } : state;
    case "verification-failed": return state.phase === "verifying" ? { phase: "verify", error: securityFailure(event.error, "verification"), check: "" } : state;
    case "validation": return { ...state, error: "Use a new password with 15–128 characters and enter the same password twice." };
    case "expired": return state.phase === "confirm" ? { phase: "verify", error: "Verification expired. Verify your password again before making this change.", check: "" } : state;
    case "mutate": return state.phase === "confirm" ? { phase: "mutating", error: "", check: "" } : state;
    case "confirmed": return state.phase === "mutating" ? { phase: "done", error: "", check: "confirmed" } : state;
    case "mutation-failed":
      if (state.phase !== "mutating") return state;
      return { phase: [403, 404, 422, 429].includes(event.error?.status) ? "verify" : "uncertain", error: securityFailure(event.error, "mutation"), check: "" };
    case "interrupted":
      if (state.phase === "done" || state.phase === "review" && (state.check === "absent" || event.preserveReview === true)) return state;
      return ["mutating", "uncertain", "checking"].includes(state.phase)
        ? { phase: "uncertain", error: "The change is unconfirmed. Check current access before any new attempt.", check: "" }
        : { phase: "verify", error: "Verify again after your sign-in is confirmed.", check: "" };
    case "check": return state.phase === "uncertain" ? { phase: "checking", error: "", check: "" } : state;
    case "checked": return state.phase === "checking" ? { phase: "review", error: "", check: event.targetAbsent ? "absent" : "active" } : state;
    case "check-failed": return state.phase === "checking" ? { phase: "uncertain", error: "Current access could not be checked. No change has been confirmed. Try checking again later.", check: "" } : state;
    case "restart": return state.phase === "review" && state.check === "active" ? securityActionState() : state;
    default: return state;
  }
}

export function createActionProofVault(owner, action, currentIdentity, now = Date.now) {
  const key = actionKey(action);
  let token = null, expiresAt = 0, csrfToken = null, identityGeneration = null;
  const clear = () => { token = null; expiresAt = 0; csrfToken = null; identityGeneration = null; };
  const current = () => currentIdentity()?.owner === owner && currentIdentity()?.active === true;
  const peek = expectedAction => {
    let expected;
    try { expected = actionKey(expectedAction); } catch { clear(); return null; }
    if (!current() || currentIdentity()?.csrfToken !== csrfToken || currentIdentity()?.generation !== identityGeneration || now() >= expiresAt || expected !== key) { clear(); return null; }
    return token;
  };
  return {
    clear,
    store(proof) {
      clear();
      if (!current()) return false;
      if (typeof proof?.proof_token !== "string" || !/^v2\.[A-Za-z0-9_-]{43}$/.test(proof.proof_token)) return false;
      const expiry = Date.parse(proof.expires_at);
      if (!Number.isFinite(expiry) || expiry <= now()) return false;
      token = proof.proof_token;
      csrfToken = currentIdentity()?.csrfToken;
      identityGeneration = currentIdentity()?.generation;
      expiresAt = Math.min(expiry, now() + 300000);
      return true;
    },
    deadline: () => expiresAt,
    peek,
    take(expectedAction) {
      const result = peek(expectedAction);
      clear();
      return result;
    }
  };
}
