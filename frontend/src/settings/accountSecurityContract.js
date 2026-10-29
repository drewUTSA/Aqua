import { accountInstant, accountOwner, compareAccountInstants } from "./accountContract.js";
const TOKEN = /^v2\.[A-Za-z0-9_-]{43}$/;
const requireValue = condition => { if (!condition) throw Error("account_action_invalid"); };
export function actionRecord(value, keys) {
  requireValue(value !== null && typeof value === "object" && !Array.isArray(value) && [Object.prototype, null].includes(Object.getPrototypeOf(value)));
  const actual = Reflect.ownKeys(value);
  requireValue(actual.length === keys.length && actual.every(key => typeof key === "string" && keys.includes(key)
    && Object.hasOwn(Object.getOwnPropertyDescriptor(value, key), "value")));
}
export function actionTarget(value) {
  const targeted = value != null && Object.hasOwn(value, "target_session_id");
  actionRecord(value, targeted ? ["operation", "target_session_id"] : ["operation"]);
  requireValue(["password_change", "session_revoke", "sessions_revoke_all"].includes(value.operation));
  requireValue(value.operation === "session_revoke" ? targeted : !targeted || value.target_session_id === null);
  return value.operation === "session_revoke" ? { operation: value.operation, target_session_id: accountOwner(value.target_session_id) } : { operation: value.operation };
}
export function actionToken(value) { requireValue(typeof value === "string" && TOKEN.test(value)); return value; }
function expiry(value, upperBound, now) {
  accountInstant(value);
  const time = Date.parse(value);
  requireValue(time > now && time <= now + 305000 && (upperBound === undefined || compareAccountInstants(value, upperBound) <= 0));
  return value;
}
export function actionChallenge(value, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "challenge_id", "challenge_token", "expires_at", "methods"]);
  requireValue(value.schemaVersion === 1 && Array.isArray(value.methods) && value.methods.length === 1 && Reflect.ownKeys(value.methods).length === 2
    && Object.hasOwn(Object.getOwnPropertyDescriptor(value.methods, "0") || {}, "value") && value.methods[0] === "password");
  return { schemaVersion: 1, challenge_id: accountOwner(value.challenge_id), challenge_token: actionToken(value.challenge_token),
    expires_at: expiry(value.expires_at, undefined, now), methods: ["password"] };
}
export function actionProof(value, challenge, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "proof_token", "expires_at"]);
  requireValue(value.schemaVersion === 1);
  return { schemaVersion: 1, proof_token: actionToken(value.proof_token), expires_at: expiry(value.expires_at, challenge.expires_at, now) };
}
export function actionPassword(value, establish = false) {
  requireValue(typeof value === "string" && [...value].length > 0 && [...value].length <= 512);
  if (establish) {
    const normalized = value.normalize("NFC");
    requireValue([...normalized].length >= 15 && [...normalized].length <= 128 && !/[\p{Cc}\p{Cs}]/u.test(normalized) && new TextEncoder().encode(normalized).byteLength <= 512);
  }
  return value; // No truncation, trimming, or change to the current password.
}
export function passwordChanged(value) {
  actionRecord(value, ["schemaVersion", "password_changed", "current_session_revoked"]);
  requireValue(value.schemaVersion === 1 && value.password_changed === true && value.current_session_revoked === true);
  return { schemaVersion: 1, password_changed: true, current_session_revoked: true };
}
export function sessionsRevoked(value, expectedCurrent) {
  actionRecord(value, ["schemaVersion", "revoked", "current_session_revoked"]);
  requireValue(typeof expectedCurrent === "boolean" && value.schemaVersion === 1 && value.revoked === true && value.current_session_revoked === expectedCurrent);
  return { schemaVersion: 1, revoked: true, current_session_revoked: expectedCurrent };
}
