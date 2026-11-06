import { accountOwner } from "./accountContract.js";
import { deletionScope } from "./dataDeletionContract.js";
import { captureHistory, deletionHistory } from "../services/historyAuthority.js";
export const initialDeletion = () => ({ phase: "review", job: null, error: "" });
export function deletionReducer(state, event) {
  if (event.type === "reset") return initialDeletion();
  if (event.type === "expired") return { phase: "expired", job: null, error: "This page's deletion receipt expired. Expiry does not confirm completion; no new deletion was sent." };
  if (event.type === "verify" && state.phase === "review") return { ...state, phase: "verify", error: "" };
  if (event.type === "verifying" && state.phase === "verify") return { ...state, phase: "verifying", error: "" };
  if (event.type === "verified" && state.phase === "verifying") return { ...state, phase: "confirm", error: "" };
  if (event.type === "verification-failed" && ["verify", "verifying", "confirm"].includes(state.phase)) return { ...state, phase: "verify", error: "Verify again for this exact deletion before continuing." };
  if (event.type === "submit" && state.phase === "confirm") return { ...state, phase: "submitting", error: "" };
  if (event.type === "uncertain" && ["submitting", "checking"].includes(state.phase)) return { ...state, phase: "uncertain", error: state.job?.accepted === true
    ? "Deletion was accepted, but the latest cleanup status could not be confirmed. Check this exact receipt; no deletion request will be replayed."
    : "Deletion is unconfirmed. Check this exact request; no deletion request will be replayed." };
  if (event.type === "check" && ["uncertain", "observing"].includes(state.phase)) return { ...state, phase: "checking", error: "" };
  if (event.type === "reply" && ["submitting", "checking"].includes(state.phase)) return { phase: "observing", job: event.job, error: "" };
  return state;
}
// The sole receipt remains in this closure. Reducer, URL and persistence never
// receive the token, CSRF value, password, proof or private workspace contents.
export function createDeletionReceipt(owner, csrf, scope, now = Date.now) {
  accountOwner(owner); deletionScope(scope);
  if (typeof csrf !== "string" || !csrf || csrf.length > 512 || /[\r\n]/.test(csrf)) throw Error("deletion_context_invalid");
  const intent = crypto.randomUUID(), history = captureHistory(csrf);
  if (history.owner && history.owner !== owner) throw Error("deletion_context_invalid");
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  let token = "v2." + btoa(String.fromCharCode(...bytes)).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); bytes.fill(0);
  let deadline = now() + 600000, attempted = false, job = null, historyHandled = false;
  const active = () => token !== null && now() < deadline;
  return Object.freeze({
    owner, csrf, scope, intent, history,
    current: active, deadline: () => deadline, attempted: () => attempted,
    attempt() { if (!active() || attempted) return false; attempted = true; return true; },
    context() { if (!active()) throw Error("deletion_receipt_expired"); return { owner, scope, intent, job }; },
    token() { if (!active()) throw Error("deletion_receipt_expired"); return token; },
    accept(reply) { if (!active() || job && reply.job.id !== job) return false; job = reply.job.id; deadline = Math.min(deadline, Date.parse(reply.job.receipt_expires_at)); return active(); },
    applyHistoryRevision(revision) {
      if (!active() || historyHandled) return false;
      historyHandled = true;
      // Only the exact original authority can advance once. Opaque tags have
      // no ordering; old receipt metadata never refreshes a replaced context.
      return deletionHistory(history, revision);
    },
    clear() { token = null; deadline = 0; job = null; },
    matches(auth) { return active() && (!auth.user ? attempted : auth.user.id === owner && auth.csrfToken === csrf); }
  });
}
