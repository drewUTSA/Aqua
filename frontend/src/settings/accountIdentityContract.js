import { accountOwner, accountRevision } from "./accountContract.js";
import { actionRecord, actionToken, actionExpiry, actionEmail } from "./accountSecurityContract.js";
const requireValue = value => { if (!value) throw Error("identity_action_invalid"); };
export function googleCredential(value) {
  requireValue(typeof value === "string" && value.length > 0 && value.length <= 8192 && new TextEncoder().encode(value).byteLength<=8192 && !/[\s\p{C}]/u.test(value));
  return value;
}
export function googleActionChallenge(value, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "challenge_id", "challenge_token", "expires_at", "client_id", "nonce"]);
  requireValue(value.schemaVersion === 1 && typeof value.client_id === "string" && value.client_id.length <= 512
    && /^[A-Za-z0-9._-]+\.apps\.googleusercontent\.com$/.test(value.client_id));
  requireValue(typeof value.nonce === "string" && /^[A-Za-z0-9_-]{43}$/.test(value.nonce));
  return { schemaVersion: 1, challenge_id: accountOwner(value.challenge_id), challenge_token: actionToken(value.challenge_token), expires_at: actionExpiry(value.expires_at, undefined, now), client_id: value.client_id, nonce: value.nonce };
}
export function googleCandidate(value, challenge, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "candidate_token", "expires_at", "google"]); actionRecord(value.google, ["email"]);
  requireValue(value.schemaVersion === 1);
  actionEmail(value.google.email);
  return { schemaVersion: 1, candidate_token: actionToken(value.candidate_token), expires_at: actionExpiry(value.expires_at, challenge.expires_at, now), google: { email: value.google.email } };
}
export function identityMutation(value, field) {
  requireValue(["linked", "unlinked", "password_added", "email_changed"].includes(field));
  actionRecord(value, ["schemaVersion", field, "current_session_revoked"]);
  requireValue(value.schemaVersion === 1 && value[field] === true && value.current_session_revoked === true);
  return { schemaVersion: 1, [field]: true, current_session_revoked: true };
}
export function mailRequest(value, operation, now = Date.now()) {
  requireValue(["password_add", "email_change"].includes(operation));
  actionRecord(value, ["schemaVersion", "request_id", "request_token", "expires_at", "confirmation_required"]);
  requireValue(value.schemaVersion === 1 && value.confirmation_required === (operation === "password_add" ? "primary_email" : "old_and_new_email"));
  return { schemaVersion: 1, request_id: accountOwner(value.request_id), request_token: actionToken(value.request_token), expires_at: actionExpiry(value.expires_at, undefined, now, 1805000), confirmation_required: value.confirmation_required };
}
export function mailToken(value) { requireValue(typeof value === "string" && /^[A-Za-z0-9_-]{43}$/.test(value)); return value; }
export function notificationValues(value) {
  actionRecord(value, ["in_app_success", "preview"]);
  requireValue(typeof value.in_app_success === "boolean" && ["generic", "hidden"].includes(value.preview));
  return { in_app_success: value.in_app_success, preview: value.preview };
}
export function notificationSnapshot(value, expectedOwner) {
  actionRecord(value, ["schemaVersion", "user_id", "revision", "values", "capabilities"]);
  requireValue(value.schemaVersion === 1 && accountOwner(value.user_id) === accountOwner(expectedOwner));
  const caps = { in_app: true, browser: false, email: false, sound: false, quiet_hours: false };
  actionRecord(value.capabilities, Object.keys(caps)); requireValue(Object.entries(caps).every(([key, enabled]) => value.capabilities[key] === enabled));
  return { schemaVersion: 1, user_id: expectedOwner, revision: accountRevision(value.revision), values: notificationValues(value.values), capabilities: caps };
}
