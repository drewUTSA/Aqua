import { accountInstant, accountOwner } from "./accountContract.js";
import { actionRecord, actionToken } from "./accountSecurityContract.js";
import { exportIntent } from "./dataExportContract.js";
import { validHistoryRevision } from "../services/historyAuthority.js";
export const DELETION_SCOPES = Object.freeze({ chat_history_v1: { operation: "history_delete", confirmation: "DELETE HISTORY", title: "Delete saved history" }, account_v1: { operation: "account_delete", confirmation: "DELETE ACCOUNT", title: "Delete account" } });
const requireValue = condition => { if (!condition) throw Error("deletion_contract_invalid"); };
export function deletionScope(scope) { requireValue(Object.hasOwn(DELETION_SCOPES, scope)); return scope; }
export function deletionStart(value) {
  actionRecord(value, ["intent_id", "scope", "proof_token", "confirmation", "receipt_token"]);
  const scope = deletionScope(value.scope);
  requireValue(value.proof_token !== value.receipt_token);
  requireValue(value.confirmation === DELETION_SCOPES[scope].confirmation);
  return { intent_id: exportIntent(value.intent_id), scope, proof_token: actionToken(value.proof_token), confirmation: value.confirmation, receipt_token: actionToken(value.receipt_token) };
}
export function deletionReply(value, context, status, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "user_id", "job", "history_revision"]);
  requireValue(value.schemaVersion === 1 && accountOwner(value.user_id) === context.owner && validHistoryRevision(value.history_revision));
  const job = value.job;
  actionRecord(job, ["id", "intent_id", "scope", "state", "accepted", "cleanup_complete", "created_at", "receipt_expires_at"]);
  accountOwner(job.id); exportIntent(job.intent_id); deletionScope(job.scope);
  requireValue(job.intent_id === context.intent && job.scope === context.scope && (!context.job || job.id === context.job));
  requireValue(["awaiting_authority", "accepted", "purging", "complete"].includes(job.state));
  requireValue(typeof job.accepted === "boolean" && job.accepted === (job.state !== "awaiting_authority")
    && typeof job.cleanup_complete === "boolean" && job.cleanup_complete === (job.state === "complete") && (status !== 202 || job.accepted));
  accountInstant(job.created_at); accountInstant(job.receipt_expires_at);
  const created = Date.parse(job.created_at), expires = Date.parse(job.receipt_expires_at);
  requireValue(expires > now && created <= now + 5000 && expires > created && expires - created <= 600000);
  return { schemaVersion: 1, user_id: context.owner, job: { ...job }, history_revision: value.history_revision };
}
