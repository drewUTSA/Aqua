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
  const keys = value !== null && typeof value === "object" ? Reflect.ownKeys(value) : [];
  const operation = Object.getOwnPropertyDescriptor(value || {}, "operation")?.value;
  requireValue(["password_change", "password_add", "email_change", "google_link", "google_unlink", "session_revoke", "sessions_revoke_all"].includes(operation));
  const target = operation === "session_revoke" ? "target_session_id" : operation === "google_unlink" ? "target_identity_id" : operation === "email_change" ? "new_email" : null;
  // Retain B's explicit-null session target compatibility, without accepting
  // target fields belonging to another identity operation.
  const nullSession = !target && keys.includes("target_session_id");
  actionRecord(value, ["operation", ...(target ? [target] : nullSession ? ["target_session_id"] : [])]);
  if (nullSession) requireValue(value.target_session_id === null);
  return { operation, ...(target ? { [target]: target === "new_email" ? actionEmail(value[target]) : accountOwner(value[target]) } : {}) };
}
export function actionEmail(value) {
  requireValue(typeof value === "string" && value.length >= 3 && value.length <= 254 && /^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+$/.test(value));
  const [local, domain] = value.split("@");
  requireValue(local.length <= 64 && !local.startsWith(".") && !local.endsWith(".") && !local.includes("..") && domain.split(".").length >= 2
    && domain.split(".").every(label => label.length > 0 && label.length <= 63 && !label.startsWith("-") && !label.endsWith("-")));
  return value.toLowerCase();
}
export function actionToken(value) { requireValue(typeof value === "string" && TOKEN.test(value)); return value; }
export function actionExpiry(value, upperBound, now, maximum = 305000) {
  accountInstant(value);
  const time = Date.parse(value);
  requireValue(time > now && time <= now + maximum && (upperBound === undefined || compareAccountInstants(value, upperBound) <= 0));
  return value;
}
export function actionChallenge(value, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "challenge_id", "challenge_token", "expires_at", "methods"]);
  requireValue(value.schemaVersion === 1 && Array.isArray(value.methods) && value.methods.length === 1 && Reflect.ownKeys(value.methods).length === 2
    && Object.hasOwn(Object.getOwnPropertyDescriptor(value.methods, "0") || {}, "value") && value.methods[0] === "password");
  return { schemaVersion: 1, challenge_id: accountOwner(value.challenge_id), challenge_token: actionToken(value.challenge_token),
    expires_at: actionExpiry(value.expires_at, undefined, now), methods: ["password"] };
}
export function actionProof(value, challenge, now = Date.now()) {
  actionRecord(value, ["schemaVersion", "proof_token", "expires_at"]);
  requireValue(value.schemaVersion === 1);
  return { schemaVersion: 1, proof_token: actionToken(value.proof_token), expires_at: actionExpiry(value.expires_at, challenge.expires_at, now) };
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
