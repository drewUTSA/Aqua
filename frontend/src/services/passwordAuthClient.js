import { sessionResponse } from "./authClient.js";

const ROOT = "/api/v1/auth";
const RESPONSE_BYTES = 16 * 1024;
const DEADLINE_MS = 30000;
const ACK = "If this address is eligible, account instructions will be sent.";
const ROUTES = Object.freeze({
  registration: ["/registrations", 202],
  verification: ["/email-verifications", 204],
  login: ["/password-login", 200],
  "reset-request": ["/password-reset-requests", 202],
  reset: ["/password-resets", 204]
});
const MESSAGES = {
  unavailable: "This account action is temporarily unavailable. Please try again later.",
  credentials_rejected: "Email or password could not be verified.",
  challenge_expired: "Please start a new authentication attempt and try again.",
  invalid_input: "Check that your email and password meet the supported requirements.",
  invalid_proof: "This link is invalid or expired. Please request a new one.",
  throttled: "Too many authentication attempts. Wait before trying again.",
  invalid_response: "AQUA could not confirm this account action. Please try again later.",
  busy: "An account action is already in progress. Please wait."
};

export class PasswordAuthError extends Error {
  constructor(status, code, retryAfterSeconds = null) {
    super(MESSAGES[code] ?? MESSAGES.unavailable);
    this.name = "PasswordAuthError";
    this.status = status;
    this.code = Object.hasOwn(MESSAGES, code) ? code : "unavailable";
    this.retryAfterSeconds = retryAfterSeconds;
  }
}

const invalidResponse = () => new PasswordAuthError(502, "invalid_response");
const cancelled = () => new DOMException("Request cancelled", "AbortError");
function checkAbort(signal) { if (signal?.aborted) throw cancelled(); }
function object(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }

function retryAfter(response) {
  const value = response.headers.get("Retry-After");
  if (!value || value.length > 64) return null;
  const seconds = /^\d{1,5}$/.test(value)
    ? Number(value) : Math.ceil((Date.parse(value) - Date.now()) / 1000);
  return Number.isFinite(seconds) && seconds >= 0 && seconds <= 86400 ? seconds : null;
}

function httpError(response) {
  const code = { 400: "invalid_proof", 401: "credentials_rejected", 403: "challenge_expired",
    422: "invalid_input", 429: "throttled" }[response.status] ?? "unavailable";
  return new PasswordAuthError(response.status, code, response.status === 429 ? retryAfter(response) : null);
}

async function discard(response) {
  try { await response.body?.cancel(); } catch { /* The safe status remains authoritative. */ }
}

async function readJson(response, signal) {
  const type = response.headers.get("Content-Type")?.split(";", 1)[0].trim().toLowerCase();
  const length = response.headers.get("Content-Length");
  if (type !== "application/json" || (length !== null && (!/^\d{1,10}$/.test(length) || Number(length) > RESPONSE_BYTES))
    || !response.body?.getReader) {
    await discard(response);
    throw invalidResponse();
  }
  const reader = response.body.getReader();
  const chunks = [];
  let size = 0;
  try {
    while (true) {
      checkAbort(signal);
      const { value, done } = await reader.read();
      checkAbort(signal);
      if (done) break;
      size += value.byteLength;
      if (size > RESPONSE_BYTES) throw invalidResponse();
      chunks.push(value);
    }
    const bytes = new Uint8Array(size);
    let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    return JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(bytes));
  } catch (error) {
    try { await reader.cancel(); } catch { /* No server body is exposed on failure. */ }
    if (error?.name === "AbortError") throw error;
    throw invalidResponse();
  } finally {
    reader.releaseLock();
  }
}

async function request(path, expectedStatus, signal, payload, csrfToken) {
  checkAbort(signal);
  let response;
  try {
    response = await fetch(`${ROOT}${path}`, {
      method: payload ? "POST" : "GET", credentials: "same-origin", mode: "same-origin",
      cache: "no-store", redirect: "error", referrerPolicy: "no-referrer", signal,
      headers: { Accept: "application/json", ...(payload ? {
        "Content-Type": "application/json", "X-CSRF-Token": csrfToken
      } : {}) },
      ...(payload ? { body: JSON.stringify(payload) } : {})
    });
  } catch (error) {
    if (signal.aborted || error?.name === "AbortError") throw cancelled();
    throw new PasswordAuthError(503, "unavailable");
  }
  if (signal.aborted) { await discard(response); throw cancelled(); }
  if (response.redirected) { await discard(response); throw invalidResponse(); }
  if (!response.ok) { const error = httpError(response); await discard(response); throw error; }
  if (response.status !== expectedStatus) { await discard(response); throw invalidResponse(); }
  return expectedStatus === 204 ? null : readJson(response, signal);
}

function bootstrapResponse(body) {
  const policy = body?.password_policy;
  const capabilities = body?.capabilities;
  if (!object(body) || typeof body.csrf_token !== "string" || !body.csrf_token
    || body.csrf_token.length > 512 || /[\r\n]/.test(body.csrf_token)
    || !object(capabilities) || Object.keys(capabilities).length !== 3
    || typeof capabilities.google_login !== "boolean" || capabilities.password_login !== true
    || capabilities.durable_sessions !== true || !object(policy) || Object.keys(policy).length !== 3
    || policy.minimum_length !== 15 || policy.maximum_length !== 128 || policy.normalization !== "NFC") {
    throw invalidResponse();
  }
  return body.csrf_token;
}

function validatePayload(action, payload) {
  if (Object.hasOwn(payload, "email") && (typeof payload.email !== "string"
    || payload.email.length < 3 || payload.email.length > 254 || /[\r\n\u0000]/.test(payload.email))) {
    throw new PasswordAuthError(422, "invalid_input");
  }
  // Bound raw input without trimming, normalizing or truncating a password. The
  // server owns the full policy and applies the same NFC rule at login and setup.
  if (Object.hasOwn(payload, "password") && (typeof payload.password !== "string"
    || !payload.password || payload.password.length > 1024 || [...payload.password].length > 512)) {
    throw new PasswordAuthError(422, "invalid_input");
  }
  if (["verification", "reset"].includes(action) && (typeof payload.token !== "string"
    || !/^[A-Za-z0-9_-]{43}$/.test(payload.token))) {
    throw new PasswordAuthError(400, "invalid_proof");
  }
}

// All anonymous actions share one host-only cookie. Refuse overlapping actions
// in this document instead of coalescing POSTs or overwriting each other's proof.
// Separate tabs still rely on the server's action binding and single-use checks.
let actionInFlight = false;
async function perform(action, payload, signal) {
  checkAbort(signal);
  validatePayload(action, payload);
  if (actionInFlight) throw new PasswordAuthError(409, "busy");
  actionInFlight = true;
  const controller = new AbortController();
  const abort = () => controller.abort();
  signal?.addEventListener("abort", abort, { once: true });
  let timedOut = false;
  const timer = setTimeout(() => { timedOut = true; controller.abort(); }, DEADLINE_MS);
  try {
    const csrf = bootstrapResponse(await request(`/bootstrap?action=${action}`, 200, controller.signal));
    checkAbort(controller.signal);
    const [path, status] = ROUTES[action];
    const body = await request(path, status, controller.signal, payload, csrf);
    checkAbort(controller.signal);
    if (action === "login") {
      try { return sessionResponse(body); } catch { throw invalidResponse(); }
    }
    if (status === 202) {
      if (!object(body) || Object.keys(body).length !== 1 || body.detail !== ACK) throw invalidResponse();
      return { accepted: true };
    }
    return null;
  } catch (error) {
    if (timedOut) throw new PasswordAuthError(503, "unavailable");
    if (signal?.aborted || error?.name === "AbortError") throw cancelled();
    if (error instanceof PasswordAuthError) throw error;
    throw invalidResponse();
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
    actionInFlight = false;
  }
}

export const requestRegistration = ({ email, signal } = {}) => perform("registration", { email }, signal);
export const completeEmailVerification = ({ token, password, signal } = {}) => perform("verification", { token, password }, signal);
export const signInWithPassword = ({ email, password, signal } = {}) => perform("login", { email, password }, signal);
export const requestPasswordReset = ({ email, signal } = {}) => perform("reset-request", { email }, signal);
export const completePasswordReset = ({ token, password, signal } = {}) => perform("reset", { token, password }, signal);
