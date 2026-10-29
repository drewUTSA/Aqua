import assert from "node:assert/strict";
import test from "node:test";
import { normalizeDisplayName, readAccount, readAccountMethods, readAccountSessions, saveAccountName } from "../src/settings/accountClient.js";
import { accountMethods, accountProfile, accountSessions } from "../src/settings/accountContract.js";
import { WorkspaceError } from "../src/services/workspaceClient.js";

const OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const ID = "cccccccc-cccc-4ccc-8ccc-cccccccccccc", NEXT = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const CAPS = { profile_edit: true, method_list: true, session_list: true, recent_proof: false,
  email_change: false, password_change: false, password_add: false, google_link: false, google_unlink: false,
  session_revoke: false, sessions_revoke_all: false, notification_delivery: false };
const profile = () => ({ schemaVersion: 1, revision: 7, user: { id: OWNER, name: "Example Person", picture: "", email: "person@example.invalid" }, email_verified: true, capabilities: { ...CAPS } });
const methods = () => ({ schemaVersion: 1, password: { linked: true, available: false, changed_at: "2026-10-26T10:00:00.123456+00:00" },
  google: { linked: true, available: true, identities: [{ id: ID, linked_at: "2026-10-26T10:00:00+00:00" }] }, capabilities: { ...CAPS } });
const session = (id = ID, current = true) => ({ id, method: "password", device_label: "Unknown device", current,
  created_at: "2026-10-26T10:00:00+00:00", authenticated_at: "2026-10-26T10:00:00+00:00", last_activity_at: "2026-10-26T10:05:00.000001+00:00",
  idle_expires_at: "2026-10-26T11:00:00+00:00", absolute_expires_at: "2026-10-27T10:00:00+00:00" });
const sessions = () => ({ schemaVersion: 1, items: [session()], capabilities: { revoke_one: false, revoke_all: false } });
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const safeError = (code) => (error) => error instanceof WorkspaceError && error.code === code
  && !error.message.includes("private-secret") && !JSON.stringify(error).includes("private-secret");
const sequentialId = (index) => `11111111-1111-4111-8111-${String(index).padStart(12, "0")}`;

test("account reads use fixed private routes and existing same-origin no-store transport", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, init }); return json(url.endsWith("/methods") ? methods() : url.endsWith("/sessions") ? sessions() : profile());
  });
  assert.equal((await readAccount(OWNER, { method: "DELETE", body: { owner_id: OTHER } })).revision, 7);
  assert.equal((await readAccountMethods()).google.identities.length, 1);
  assert.equal((await readAccountSessions()).items[0].current, true);
  assert.deepEqual(calls.map(({ url }) => url), ["/api/v1/me", "/api/v1/me/methods", "/api/v1/me/sessions"]);
  for (const { init } of calls) {
    assert.equal(init.method, "GET"); assert.equal(init.body, undefined); assert.equal(init.credentials, "same-origin");
    assert.equal(init.mode, "same-origin"); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error");
    assert.equal(init.referrerPolicy, "no-referrer"); assert.equal(init.headers.Accept, "application/json");
    assert.equal(init.headers["X-CSRF-Token"], undefined);
  }
});

test("display-name update sends only normalized closed CAS fields and CSRF", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json({ ...profile(), revision: 8, user: { ...profile().user, name: "Jos\u00e9" } }); });
  await saveAccountName(OWNER, { revision: 7, name: "  Jose\u0301  " }, { csrfToken: "bound-csrf", method: "POST", body: { role: "admin" } });
  assert.equal(calls.length, 1); assert.equal(calls[0].url, "/api/v1/me");
  assert.equal(calls[0].init.method, "PATCH"); assert.equal(calls[0].init.headers["X-CSRF-Token"], "bound-csrf");
  assert.equal(calls[0].init.headers["Content-Type"], "application/json");
  assert.deepEqual(JSON.parse(calls[0].init.body), { expectedRevision: 7, display_name: "Jos\u00e9" });
  assert.equal(calls[0].init.credentials, "same-origin"); assert.equal(calls[0].init.cache, "no-store"); assert.equal(calls[0].init.redirect, "error");
});

test("a write is confirmed only by the exact submitted name and one valid CAS revision step", async (t) => {
  for (const [name, revision] of [["Different name", 8], ["Entered name", 6], ["Entered name", 9], ["Entered name", Number.MAX_SAFE_INTEGER]]) {
    t.mock.method(globalThis, "fetch", async () => json({ ...profile(), revision, user: { ...profile().user, name } }));
    await assert.rejects(saveAccountName(OWNER, { revision: 7, name: "Entered name" }, { csrfToken: "csrf" }), safeError("invalid_response"));
  }
  for (const revision of [7, 8]) {
    t.mock.method(globalThis, "fetch", async () => json({ ...profile(), revision }));
    assert.equal((await saveAccountName(OWNER, { revision: 7, name: profile().user.name }, { csrfToken: "csrf" })).revision, revision);
  }
  t.mock.method(globalThis, "fetch", async () => json({ ...profile(), revision: Number.MAX_SAFE_INTEGER }));
  assert.equal((await readAccount(OWNER)).revision, Number.MAX_SAFE_INTEGER);
  assert.equal((await saveAccountName(OWNER, { revision: Number.MAX_SAFE_INTEGER, name: profile().user.name }, { csrfToken: "csrf" })).revision, Number.MAX_SAFE_INTEGER);
  t.mock.method(globalThis, "fetch", async () => json({ ...profile(), revision: Number.MAX_SAFE_INTEGER + 1 }));
  await assert.rejects(saveAccountName(OWNER, { revision: Number.MAX_SAFE_INTEGER, name: profile().user.name }, { csrfToken: "csrf" }), safeError("invalid_response"));
});

test("new names match the Unicode policy without silently dropping forbidden controls", () => {
  assert.equal(normalizeDisplayName("  Jose\u0301  "), "Jos\u00e9");
  assert.equal(normalizeDisplayName("\u{1f30a}".repeat(120)), "\u{1f30a}".repeat(120));
  assert.equal(normalizeDisplayName(" ".repeat(1500) + "A"), "A");
  for (const name of [null, 12, {}, "", "  ", "a".repeat(121), "line\n", "\tname", "a\rname", "a\0name", "a\u2028name", "a\u2029name", "a\u202ename", "a\u200dname", "a\ud800", "a\u0378"]) {
    assert.throws(() => normalizeDisplayName(name), safeError("invalid_input"));
  }
});

test("invalid owners, revisions and mass assignment fail before any network request", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("must not send"); });
  for (const owner of [undefined, "//attacker.invalid", OWNER.toUpperCase(), OWNER.replaceAll("-", ""), OTHER + "?owner=" + OWNER]) {
    assert.throws(() => readAccount(owner), safeError("invalid_input"));
  }
  for (const revision of [0, -1, 1.5, "7", 7n, Number.MAX_SAFE_INTEGER + 1, Infinity, NaN]) {
    assert.throws(() => saveAccountName(OWNER, { revision, name: "A" }, { csrfToken: "csrf" }), safeError("invalid_input"));
  }
  assert.throws(() => saveAccountName(OWNER, { revision: 7, name: "A", owner_id: OTHER }, { csrfToken: "csrf" }), safeError("invalid_input"));
  assert.throws(() => saveAccountName(OWNER, Object.defineProperty({ revision: 7 }, "name", { get() { throw new Error("private-secret"); }, enumerable: true })), safeError("invalid_input"));
  assert.throws(() => saveAccountName(OWNER, { revision: 7, name: "A", [Symbol("secret")]: "private-secret" }), safeError("invalid_input"));
  await assert.rejects(saveAccountName(OWNER, { revision: 7, name: "A" }), safeError("unauthenticated"));
  await assert.rejects(saveAccountName(OWNER, { revision: 7, name: "A" }, { csrfToken: "bad\r\nheader" }), safeError("unauthenticated"));
  assert.equal(fetch.mock.callCount(), 0);
});

test("profile identity is checked against the initiating owner on reads and saves", async (t) => {
  t.mock.method(globalThis, "fetch", async () => json({ ...profile(), user: { ...profile().user, id: OTHER } }));
  await assert.rejects(readAccount(OWNER), safeError("invalid_response"));
  await assert.rejects(saveAccountName(OWNER, { revision: 7, name: "A" }, { csrfToken: "csrf" }), safeError("invalid_response"));
});

test("profile decoder rejects unknown fields, secret material and forged capability changes", async (t) => {
  const cases = [
    { ...profile(), schemaVersion: 2 }, { ...profile(), revision: 0 }, { ...profile(), revision: Number.MAX_SAFE_INTEGER + 1 },
    { ...profile(), email_verified: false }, { ...profile(), pending_email: "private-secret" },
    { ...profile(), user: { ...profile().user, token: "private-secret" } },
    { ...profile(), user: { ...profile().user, name: "private-secret\u202e" } },
    { ...profile(), user: { ...profile().user, email: "private-secret@example.invalid\n" } },
    { ...profile(), capabilities: { ...CAPS, password_change: true } },
    { ...profile(), capabilities: { ...CAPS, profile_edit: 1 } },
    { ...profile(), capabilities: { ...CAPS, mfa: true } },
  ];
  for (const payload of cases) {
    t.mock.method(globalThis, "fetch", async () => json(payload));
    await assert.rejects(readAccount(OWNER), safeError("invalid_response"));
  }
  assert.throws(() => accountProfile({ ...profile(), revision: 7n }, OWNER), /account_invalid/);
  assert.throws(() => accountProfile(JSON.parse(JSON.stringify(profile()).replace('"schemaVersion":1', '"schemaVersion":1,"__proto__":{"polluted":true}')), OWNER), /account_invalid/);
  assert.equal(Object.prototype.polluted, undefined);
});

test("legacy empty names remain readable and successful profile records are copied", () => {
  const payload = profile(); payload.user.name = "";
  const result = accountProfile(payload, OWNER);
  assert.equal(result.user.name, ""); payload.user.name = "mutated"; payload.capabilities.profile_edit = false;
  assert.equal(result.user.name, ""); assert.equal(result.capabilities.profile_edit, true);
  const missing = profile(); delete missing.user.picture;
  assert.throws(() => accountProfile(missing, OWNER), /account_invalid/);
});

test("profile images obey the existing safe Google host policy", () => {
  for (const picture of ["", "https://lh3.googleusercontent.com/a/photo=s96-c", "https://googleusercontent.com/photo"]) {
    const payload = profile(); payload.user.picture = picture; assert.equal(accountProfile(payload, OWNER).user.picture, picture);
  }
  for (const picture of [null, "javascript:alert(1)", "data:image/svg+xml,test", "http://lh3.googleusercontent.com/a", "https://googleusercontent.com.attacker.invalid/a", "https://googleusercontent.com@attacker.invalid/a", "https://person:secret@lh3.googleusercontent.com/a", "https://attacker.invalid/googleusercontent.com", "https://lh3.googleusercontent.com/\nphoto", "x".repeat(1025)]) {
    const payload = profile(); payload.user.picture = picture; assert.throws(() => accountProfile(payload, OWNER));
  }
});

test("method snapshots distinguish linked methods from configured availability and remain bounded", () => {
  const payload = methods(); const result = accountMethods(payload);
  assert.equal(result.password.linked, true); assert.equal(result.password.available, false);
  payload.google.identities[0].id = OTHER; assert.equal(result.google.identities[0].id, ID);
  const none = methods(); none.password = { linked: false, available: false, changed_at: null };
  none.google = { linked: false, available: false, identities: [] }; assert.equal(accountMethods(none).google.linked, false);
  const twenty = methods(); twenty.google.identities = Array.from({ length: 20 }, (_, index) => ({ id: sequentialId(index), linked_at: "2026-10-26T10:00:00Z" }));
  assert.equal(accountMethods(twenty).google.identities.length, 20);
  twenty.google.identities.push({ id: NEXT, linked_at: "2026-10-26T10:00:00Z" }); assert.throws(() => accountMethods(twenty), /account_invalid/);
});

test("closed decoders reject sparse lists, extra array properties and getter records", () => {
  const sparseMethods = methods(); sparseMethods.google.identities = new Array(1);
  assert.throws(() => accountMethods(sparseMethods), /account_invalid/);
  const extraMethods = methods(); extraMethods.google.identities.secret = "private-secret";
  assert.throws(() => accountMethods(extraMethods), /account_invalid/);
  const sparseSessions = sessions(); sparseSessions.items.length = 2;
  assert.throws(() => accountSessions(sparseSessions), /account_invalid/);
  const getter = profile(); let reads = 0;
  Object.defineProperty(getter.user, "name", { get() { reads += 1; return "private-secret"; } });
  assert.throws(() => accountProfile(getter, OWNER), /account_invalid/); assert.equal(reads, 0);
  const inherited = Object.create(profile()); assert.throws(() => accountProfile(inherited, OWNER), /account_invalid/);
});

test("method DTOs reject inconsistent booleans, provider subjects, duplicates and malformed dates", async (t) => {
  const mutations = [
    (v) => { v.password.available = "true"; }, (v) => { v.password.linked = false; },
    (v) => { v.password.changed_at = null; }, (v) => { v.password.encoded_hash = "private-secret"; },
    (v) => { v.google.linked = false; }, (v) => { v.google.identities.push({ ...v.google.identities[0] }); },
    (v) => { v.google.identities[0].subject = "private-secret"; }, (v) => { v.google.identities[0].id = "not-a-uuid"; },
    (v) => { v.capabilities.google_link = true; }, (v) => { v.capabilities.notification_delivery = true; },
  ];
  for (const changed_at of ["yesterday", "2026-02-30T10:00:00Z", "2026-01-01T24:00:00Z", "2026-01-01T10:00:00", "2026-01-01T10:00:00.1234567Z", "2026-01-01T10:00:00+14:01", 10, {}]) mutations.push((v) => { v.password.changed_at = changed_at; });
  for (const mutate of mutations) {
    const payload = methods(); mutate(payload); t.mock.method(globalThis, "fetch", async () => json(payload));
    await assert.rejects(readAccountMethods(), safeError("invalid_response"));
  }
});

test("session snapshots require one current first, bound the list and copy safe coarse labels", () => {
  const payload = sessions(); payload.items.push({ ...session(NEXT, false), device_label: "Desktop browser" });
  const result = accountSessions(payload); assert.equal(result.items[1].device_label, "Desktop browser");
  payload.items[1].device_label = "private-secret IP/location text";
  assert.equal(accountSessions(payload).items[1].device_label, "Unknown device");
  assert.equal(result.items[1].device_label, "Desktop browser");
  const twenty = sessions(); twenty.items = Array.from({ length: 20 }, (_, index) => session(sequentialId(index), index === 0));
  assert.equal(accountSessions(twenty).items.length, 20);
  twenty.items.push(session(NEXT, false)); assert.throws(() => accountSessions(twenty), /account_invalid/);
});

test("session DTOs reject secrets, unknown authority, duplicate identities and impossible timestamp order", async (t) => {
  const mutations = [
    (v) => { v.items = []; }, (v) => { v.items[0].current = false; },
    (v) => { v.items.push(session(NEXT)); }, (v) => { v.items.unshift(session(NEXT, false)); },
    (v) => { v.items.push(session(ID, false)); }, (v) => { v.items[0].current = 1; },
    (v) => { v.items[0].method = "linked"; }, (v) => { v.items[0].csrf_digest = "private-secret"; },
    (v) => { v.items[0].location = "private-secret"; }, (v) => { v.items[0].user_id = OWNER; },
    (v) => { v.items[0].device_label = "raw\nuser-agent"; }, (v) => { v.items[0].device_label = "x".repeat(121); },
    (v) => { v.items[0].created_at = "2026-10-26T10:01:00Z"; },
    (v) => { v.items[0].authenticated_at = "2026-10-26T10:06:00Z"; },
    (v) => { v.items[0].idle_expires_at = "2026-10-26T10:05:00Z"; },
    (v) => { v.items[0].absolute_expires_at = "2026-10-26T10:59:59Z"; },
    (v) => { v.capabilities.revoke_one = true; }, (v) => { v.capabilities.revoke_all = true; },
    (v) => { v.capabilities.owner = "private-secret"; },
  ];
  for (const mutate of mutations) {
    const payload = sessions(); mutate(payload); t.mock.method(globalThis, "fetch", async () => json(payload));
    await assert.rejects(readAccountSessions(), safeError("invalid_response"));
  }
});

test("microsecond session ordering and timestamp offsets remain exact", () => {
  const payload = sessions();
  payload.items.push({ ...session(NEXT, false), last_activity_at: "2026-10-26T10:05:00.000002+00:00" }, { ...session(OTHER, false), last_activity_at: "2026-10-26T11:05:00.000001+01:00" });
  assert.equal(accountSessions(payload).items.length, 3);
  [payload.items[1], payload.items[2]] = [payload.items[2], payload.items[1]];
  assert.throws(() => accountSessions(payload), /account_invalid/);
});

for (const [status, code] of [[401, "unauthenticated"], [403, "forbidden"], [404, "not_found"], [409, "conflict"], [422, "invalid_input"], [429, "throttled"], [503, "unavailable"]]) {
  test(`account HTTP ${status} returns safe fixed feedback without reflection or automatic retry`, async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => json({ error: { message: "private-secret", proof: "private-secret" } }, status, { "Retry-After": "30" }));
    await assert.rejects(saveAccountName(OWNER, { revision: 7, name: "Entered name" }, { csrfToken: "csrf" }), safeError(code));
    assert.equal(fetch.mock.callCount(), 1);
  });
}

test("redirects, unexpected status and malformed transport payloads never become account state", async (t) => {
  const redirected = json(profile()); Object.defineProperty(redirected, "redirected", { value: true });
  const responses = [redirected, json(profile(), 201), json(profile(), 200, { "Content-Type": "text/html" }),
    new Response('{"private-secret":', { headers: { "Content-Type": "application/json" } }),
    json(profile(), 200, { "Content-Length": String(6 * 1024 * 1024 + 1) })];
  for (const response of responses) {
    t.mock.method(globalThis, "fetch", async () => response);
    await assert.rejects(readAccount(OWNER, { expectedStatuses: [200, 201] }), (error) => error instanceof WorkspaceError && !error.message.includes("private-secret"));
  }
});

test("a lost write response stays unconfirmed and requires a separate explicit read to reconcile", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (url, init) => {
    calls.push({ url, method: init.method });
    if (init.method === "PATCH") throw new Error("private-secret offline provider detail");
    return json({ ...profile(), revision: 8, user: { ...profile().user, name: "Entered name" } });
  });
  await assert.rejects(saveAccountName(OWNER, { revision: 7, name: "Entered name" }, { csrfToken: "csrf" }), (error) => error instanceof WorkspaceError && !error.message.includes("private-secret"));
  assert.equal(calls.length, 1); assert.equal((await readAccount(OWNER)).user.name, "Entered name");
  assert.deepEqual(calls, [{ url: "/api/v1/me", method: "PATCH" }, { url: "/api/v1/me", method: "GET" }]);
});

test("aborted account scope cannot publish a late read or write result", async (t) => {
  for (const request of [(options) => readAccount(OWNER, options), readAccountMethods, readAccountSessions,
    (options) => saveAccountName(OWNER, { revision: 7, name: "A" }, { ...options, csrfToken: "csrf" })]) {
    const controller = new AbortController(); let resolveFetch;
    const fetch = t.mock.method(globalThis, "fetch", () => new Promise((resolve) => { resolveFetch = resolve; }));
    const pending = request({ signal: controller.signal }); controller.abort(); resolveFetch(json(profile()));
    await assert.rejects(pending, { name: "AbortError" }); assert.equal(fetch.mock.callCount(), 1);
  }
  const controller = new AbortController(); controller.abort();
  const fetch = t.mock.method(globalThis, "fetch", async () => json(profile()));
  await assert.rejects(readAccount(OWNER, { signal: controller.signal }), { name: "AbortError" }); assert.equal(fetch.mock.callCount(), 0);
});

test("abort while consuming the body discards a completed account JSON stream", async (t) => {
  const controller = new AbortController(); const encoded = new TextEncoder().encode(JSON.stringify(profile()));
  const stream = new ReadableStream({ start(control) { control.enqueue(encoded); controller.abort(); control.close(); } });
  t.mock.method(globalThis, "fetch", async () => new Response(stream, { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(readAccount(OWNER, { signal: controller.signal }), { name: "AbortError" });
});
