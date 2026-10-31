import assert from "node:assert/strict";
import test from "node:test";
import { createAccountChallenge, verifyAccountPassword, changeAccountPassword, revokeAccountSession, revokeAllAccountSessions } from "../src/settings/accountSecurityClient.js";
import { actionChallenge, actionProof, actionTarget, actionPassword } from "../src/settings/accountSecurityContract.js";
import { accountProfile } from "../src/settings/accountContract.js";
import { WorkspaceError } from "../src/services/workspaceClient.js";

const ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const TOKEN = "v2." + "a".repeat(43), PROOF = "v2." + "b".repeat(43), CURRENT = "Synthetic current password 25", NEW = "  Synthetic new password 27  ";
const target = { operation: "session_revoke", target_session_id: OTHER };
const challenge = () => ({ schemaVersion: 1, challenge_id: ID, challenge_token: TOKEN, expires_at: new Date(Date.now() + 240000).toISOString(), methods: ["password"] });
const proof = () => ({ schemaVersion: 1, proof_token: PROOF, expires_at: new Date(Date.now() + 180000).toISOString() });
const ack = current => ({ schemaVersion: 1, revoked: true, current_session_revoked: current });
const json = (body, status = 200, extra = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...extra } });
const safe = code => error => error instanceof WorkspaceError && error.code === code && !JSON.stringify(error).includes(TOKEN)
  && !error.message.includes(CURRENT) && !error.message.includes(NEW) && !error.message.includes("private-server-data");
const caps = { profile_edit: true, method_list: true, session_list: true, recent_proof: true, password_change: true, password_add: false,
  email_change: false, google_link: false, google_unlink: false, session_revoke: true, sessions_revoke_all: true, notification_delivery: false, in_app_notifications: true };

test("all five security actions use exact private routes, closed bodies and independent CSRF", async t => {
  const calls = [], issued = challenge();
  t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, init });
    return json(url.endsWith("reauth-challenges") ? issued : url.endsWith("reauth/password") ? proof()
      : url.endsWith("/password") ? { schemaVersion: 1, password_changed: true, current_session_revoked: true }
        : ack(url.endsWith("session-revocations")));
  });
  const options = { csrfToken: "synthetic-csrf", method: "DELETE", body: { owner_id: ID }, expectedStatuses: [204] };
  await createAccountChallenge(target, options);
  await verifyAccountPassword(target, issued, CURRENT, options);
  await changeAccountPassword(PROOF, NEW, options);
  await revokeAccountSession(OTHER, PROOF, false, options);
  await revokeAllAccountSessions(PROOF, options);
  assert.deepEqual(calls.map(call => [call.url, call.init.method]), [["/api/v1/me/reauth-challenges", "POST"], ["/api/v1/me/reauth/password", "POST"],
    ["/api/v1/me/password", "PUT"], [`/api/v1/me/sessions/${OTHER}/revocations`, "POST"], ["/api/v1/me/session-revocations", "POST"]]);
  assert.deepEqual(calls.map(call => JSON.parse(call.init.body)), [target, { ...target, challenge_id: ID, challenge_token: TOKEN, password: CURRENT },
    { proof_token: PROOF, new_password: NEW }, { proof_token: PROOF }, { proof_token: PROOF }]);
  for (const { init } of calls) {
    assert.equal(init.credentials, "same-origin"); assert.equal(init.mode, "same-origin"); assert.equal(init.cache, "no-store");
    assert.equal(init.redirect, "error"); assert.equal(init.referrerPolicy, "no-referrer"); assert.equal(init.headers["X-CSRF-Token"], "synthetic-csrf");
    assert.equal(init.headers["Content-Type"], "application/json");
  }
});

test("challenge and proof replies are exact, expiring, method-bounded and copied", () => {
  const now = Date.now(), issued = challenge(), verified = proof();
  const parsed = actionChallenge(issued, now), stored = actionProof(verified, parsed, now);
  issued.methods[0] = "google"; assert.deepEqual(parsed.methods, ["password"]); assert.equal(stored.proof_token, PROOF);
  for (const bad of [{ ...challenge(), csrf_token: "private-server-data" }, { ...challenge(), methods: ["password", "google"] },
    { ...challenge(), methods: ["google"] }, { ...challenge(), methods: Array(2) }, { ...challenge(), challenge_token: "a".repeat(43) },
    { ...challenge(), challenge_id: ID.toUpperCase() }, { ...challenge(), expires_at: new Date(now - 1).toISOString() },
    { ...challenge(), expires_at: new Date(now + 306000).toISOString() }, { ...challenge(), expires_at: "2026-02-30T12:00:00Z" }]) {
    assert.throws(() => actionChallenge(bad, now));
  }
  for (const bad of [{ ...proof(), request_id: "private-server-data" }, { ...proof(), proof_token: TOKEN + "x" },
    { ...proof(), expires_at: new Date(now + 250000).toISOString() }, { ...proof(), expires_at: new Date(now - 1).toISOString() }]) {
    assert.throws(() => actionProof(bad, parsed, now));
  }
});

test("action targets exclude owner authority, future operations and target aliases before network", t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw Error("must not send"); });
  for (const value of [{ operation: "email_change" }, { operation: "password_add" }, { operation: "account_delete" }, { operation: "session_revoke" },
    { ...target, target_session_id: "../other" }, { ...target, owner_id: ID }, { operation: "password_change", target_session_id: OTHER },
    { operation: "sessions_revoke_all", target_session_id: OTHER }, Object.defineProperty({}, "operation", { get() { throw Error("private-server-data"); }, enumerable: true })]) {
    assert.throws(() => createAccountChallenge(value, { csrfToken: "csrf" }), safe("invalid_input"));
  }
  assert.deepEqual(actionTarget({ operation: "password_change", target_session_id: null }), { operation: "password_change" });
  assert.deepEqual(actionTarget({ operation: "sessions_revoke_all" }), { operation: "sessions_revoke_all" });
  assert.equal(fetch.mock.calls.length, 0);
});

test("an in-flight proof response remains bound to the captured challenge expiry", async t => {
  const issued = challenge();
  t.mock.method(globalThis, "fetch", async () => {
    issued.expires_at = new Date(Date.now() + 300000).toISOString();
    return json({ ...proof(), expires_at: new Date(Date.now() + 280000).toISOString() });
  });
  await assert.rejects(verifyAccountPassword(target, issued, CURRENT, { csrfToken: "csrf" }), safe("invalid_response"));
});

test("proof expiry cannot exceed its challenge by even one PostgreSQL microsecond", () => {
  const second = Math.floor(Date.now() / 1000) * 1000 + 60000, base = new Date(second).toISOString().slice(0, 19);
  const issued = { ...challenge(), expires_at: base + ".000001Z" };
  assert.throws(() => actionProof({ ...proof(), expires_at: base + ".000002Z" }, issued));
  assert.equal(actionProof({ ...proof(), expires_at: base + ".000001Z" }, issued).proof_token, PROOF);
});

test("password inputs remain complete raw strings and establishment policy matches NFC bounds", t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw Error("must not send"); });
  assert.equal(actionPassword(CURRENT), CURRENT); assert.equal(actionPassword(NEW, true), NEW);
  assert.equal(actionPassword("Synthetic e\u0301 password 27", true), "Synthetic e\u0301 password 27");
  assert.equal(actionPassword("🌊".repeat(128), true), "🌊".repeat(128));
  for (const value of [null, [], "", "a".repeat(513)]) assert.throws(() => verifyAccountPassword(target, challenge(), value, { csrfToken: "csrf" }), safe("invalid_input"));
  for (const value of ["short", "🌊".repeat(129), "  short  ", "Synthetic\nnew password", "Synthetic\ud800 password 27"]) {
    assert.throws(() => changeAccountPassword(PROOF, value, { csrfToken: "csrf" }), safe("invalid_input"));
  }
  assert.equal(fetch.mock.calls.length, 0);
});

test("missing CSRF cannot issue a challenge, prove identity, or mutate security", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw Error("must not send"); });
  for (const invoke of [() => createAccountChallenge(target), () => verifyAccountPassword(target, challenge(), CURRENT),
    () => changeAccountPassword(PROOF, NEW), () => revokeAccountSession(OTHER, PROOF, false), () => revokeAllAccountSessions(PROOF)]) {
    await assert.rejects(invoke(), safe("unauthenticated"));
  }
  assert.equal(fetch.mock.calls.length, 0);
});

test("mutation acknowledgement must match the exact requested action and current-session outcome", async t => {
  for (const result of [{ ...ack(false), revoked: false }, { ...ack(false), proof_token: PROOF }, ack(true), { ...ack(false), schemaVersion: 2 }]) {
    t.mock.method(globalThis, "fetch", async () => json(result));
    await assert.rejects(revokeAccountSession(OTHER, PROOF, false, { csrfToken: "csrf" }), safe("invalid_response"));
  }
  for (const result of [{ schemaVersion: 1, password_changed: true, current_session_revoked: false }, { schemaVersion: 1, password_changed: false, current_session_revoked: true },
    { schemaVersion: 1, password_changed: true, current_session_revoked: true, session: "private-server-data" }]) {
    t.mock.method(globalThis, "fetch", async () => json(result));
    await assert.rejects(changeAccountPassword(PROOF, NEW, { csrfToken: "csrf" }), safe("invalid_response"));
  }
});

for (const status of [401, 403, 404, 422, 429, 503]) test(`security HTTP ${status} never copies secrets or retries consumed proof/challenge`, async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => json({ error: { message: "private-server-data", password: CURRENT, proof_token: PROOF } }, status, { "Retry-After": "30" }));
  await assert.rejects(verifyAccountPassword(target, challenge(), CURRENT, { csrfToken: "csrf" }), error => safe(({ 401: "unauthenticated", 403: "forbidden", 404: "not_found", 422: "invalid_input", 429: "throttled" })[status] || "unavailable")(error)
    && (status !== 429 || error.retryAfter === 30));
  assert.equal(fetch.mock.calls.length, 1);
});

test("lost commit replies remain uncertain and no mutation replays automatically", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw Error("private-server-data " + PROOF); });
  await assert.rejects(changeAccountPassword(PROOF, NEW, { csrfToken: "csrf" }), safe("invalid_response"));
  assert.equal(fetch.mock.calls.length, 1);
});

test("aborted proof or commit response cannot become accepted authority", async t => {
  const controller = new AbortController();
  t.mock.method(globalThis, "fetch", async () => { controller.abort(); return json(proof()); });
  await assert.rejects(verifyAccountPassword(target, challenge(), CURRENT, { csrfToken: "csrf", signal: controller.signal }), { name: "AbortError" });
});

test("P10b capability decoder accepts only coherent finite implemented actions", () => {
  const snapshot = { schemaVersion: 1, revision: 1, user: { id: ID, name: "Synthetic", email: "synthetic@example.invalid", picture: "" }, email_verified: true, capabilities: caps };
  assert.equal(accountProfile(snapshot, ID).capabilities.password_change, true);
  assert.equal(accountProfile({ ...snapshot, capabilities: { ...caps, password_change: false } }, ID).capabilities.recent_proof, true);
  for (const capabilities of [{ ...caps, password_add: "yes" }, { ...caps, google_link: "yes" }, { ...caps, recent_proof: false },
    { ...caps, session_revoke: false }, { ...caps, password_change: "true" }, { ...caps, proof_token: PROOF }]) assert.throws(() => accountProfile({ ...snapshot, capabilities }, ID));
  const legacy = { ...caps }; delete legacy.password_add; assert.throws(() => accountProfile({ ...snapshot, capabilities: legacy }, ID));
});
