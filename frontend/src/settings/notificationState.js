import { notificationValues } from "./accountIdentityContract.js";
import { validId } from "../services/workspaceContract.js";
export const sameNotificationValues = (a, b) => a?.in_app_success === b?.in_app_success && a?.preview === b?.preview;
export const notificationEditor = () => ({ phase: "loading", base: null, draft: { in_app_success: false, preview: "generic" }, latest: null, attempt: null, error: "", status: "" });
export function notificationReducer(state, event) {
  switch (event.type) {
    case "loaded": return !state.base ? { ...notificationEditor(), phase: "editing", base: event.snapshot, draft: { ...event.snapshot.values } } : state;
    case "load-failed": return { ...state, phase: "unavailable", error: "Notification settings could not be loaded. Optional success messages remain off until your saved settings are confirmed." };
    case "edit": return state.phase === "editing" ? { ...state, draft: notificationValues({ ...state.draft, [event.key]: event.value }), error: "", status: "" } : state;
    case "cancel": return state.phase === "editing" ? { ...state, draft: { ...state.base.values }, error: "", status: "" } : state;
    case "save": return state.phase === "editing" ? { ...state, phase: "saving", attempt: { revision: state.base.revision, values: { ...state.draft } }, error: "", status: "" } : state;
    case "saved": return state.phase === "saving" ? { ...state, phase: "editing", base: event.snapshot, draft: { ...event.snapshot.values }, latest: null, attempt: null, status: "Notification settings saved." } : state;
    case "failed": return state.phase === "saving" ? { ...state, phase: "blocked", error: event.error?.status === 409 ? "Notification settings changed elsewhere. Reload and review your selection before saving." : "AQUA could not confirm whether these settings were saved. Your selection is still here. Check saved settings before trying again." } : state;
    case "check": return ["blocked", "unavailable"].includes(state.phase) ? { ...state, phase: "checking", error: "" } : state;
    case "checked": {
      if (state.phase !== "checking") return state;
      if (!state.base) return { ...notificationEditor(), phase: "editing", base: event.snapshot, draft: { ...event.snapshot.values } };
      if (event.snapshot.user_id !== state.base.user_id || event.snapshot.revision < state.base.revision || event.snapshot.revision === state.base.revision && !sameNotificationValues(event.snapshot.values, state.base.values)) return { ...state, phase: "blocked", error: "The saved settings revision could not be confirmed. Check again before saving." };
      if (state.attempt && event.snapshot.revision >= state.attempt.revision && sameNotificationValues(event.snapshot.values, state.attempt.values)) return { ...state, phase: "editing", base: event.snapshot, draft: { ...event.snapshot.values }, latest: null, attempt: null, status: "Saved notification settings confirmed." };
      return { ...state, phase: "review", latest: event.snapshot, error: "", status: "" };
    }
    case "check-failed": return state.phase === "checking" ? { ...state, phase: "blocked", error: "Saved notification settings could not be checked. Your selection is still here." } : state;
    case "keep":
    case "use-saved": return state.phase === "review" && state.latest ? { ...state, phase: "editing", base: state.latest, draft: event.type === "keep" ? state.draft : { ...state.latest.values }, latest: null, attempt: null, error: "" } : state;
    case "interrupted": return ["saving", "checking"].includes(state.phase) ? { ...state, phase: "blocked", error: "The change is unconfirmed. Check saved settings when your sign-in is confirmed." } : state;
    default: return state;
  }
}

// Consent and deduplication are memory-only and tied to the current auth pair.
// Callers pass only newly observed owned live transitions, never loaded history.
export function createLiveNoticeGate(owner, identity) {
  let consent = null, csrf = null; const seen = new Set();
  const reset = () => { consent = null; csrf = null; seen.clear(); };
  const current = () => identity()?.active === true && identity()?.owner === owner;
  return {
    reset,
    confirm(snapshot, expected) { if (!current() || snapshot.user_id !== owner || snapshot.capabilities?.in_app !== true || expected?.owner!==owner || expected?.csrfToken!==identity()?.csrfToken) return false;if(csrf!==identity()?.csrfToken)seen.clear();consent = { ...notificationValues(snapshot.values) }; csrf = identity()?.csrfToken; return true; },
    observe({ owner: observedOwner, requestId, previousStatus, status, live, alreadyVisible }) {
      if (!current() || identity()?.csrfToken !== csrf) { reset(); return null; }
      if (!consent?.in_app_success || consent.preview !== "generic" || observedOwner !== owner || live !== true || !["pending", "queued", "running"].includes(previousStatus) || status !== "complete" || !validId(requestId) || seen.has(requestId)) return null;
      seen.add(requestId); if (seen.size > 64) seen.delete(seen.values().next().value);
      return alreadyVisible === true ? null : { id: requestId, message: "Your request is complete." };
    }
  };
}
