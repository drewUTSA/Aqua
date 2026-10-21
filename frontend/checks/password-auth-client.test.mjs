import assert from "node:assert/strict";
import test from "node:test";
import {
  PasswordAuthError, requestRegistration, completeEmailVerification,
  signInWithPassword, requestPasswordReset, completePasswordReset
} from "../src/services/passwordAuthClient.js";
import { fetchAuthConfig, sessionResponse } from "../src/services/authClient.js";

const EMAIL = "fixture@example.test";
const PASSWORD = "  fixture password with spaces  ";
const TOKEN = "a".repeat(43);
const BOOTSTRAP = {
  csrf_token: "fixture-action-csrf",
  capabilities: { google_login: false, password_login: true, durable_sessions: true },
  password_policy: { minimum_length: 15, maximum_length: 128, normalization: "NFC" }
};
const SESSION = {
  user: { id: "7506fb3d-1119-4b29-8c57-5ea696a739a1", email: EMAIL, name: "Fixture", picture: "" },
  csrf_token: "fixture-session-csrf", can_query: false,
  capabilities: { google_login: false, password_login: true, durable_sessions: true }
};
const ACK = { detail: "If this address is eligible, account instructions will be sent." };
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), {
  status, headers: { "Content-Type": "application/json", ...headers }
});
const expectError = (code, status) => (error) => {
  assert.ok(error instanceof PasswordAuthError);
  assert.equal(error.code, code);
  assert.equal(error.status, status);
  assert.doesNotMatch(error.message, /private-server|fixture-action-csrf|fixture password|fixture@example|aaaaaaaaaaaaaaaa/);
  return true;
};

for (const [label, action, endpoint, invoke, payload, success, expected] of [
  ["email-first registration", "registration", "registrations", requestRegistration, { email: EMAIL }, () => json(ACK, 202), { accepted: true }],
  ["verified password creation", "verification", "email-verifications", completeEmailVerification, { token: TOKEN, password: PASSWORD }, () => new Response(null, { status: 204 }), null],
  ["password-only account login", "login", "password-login", signInWithPassword, { email: EMAIL, password: PASSWORD }, () => json(SESSION), SESSION],
  ["generic recovery request", "reset-request", "password-reset-requests", requestPasswordReset, { email: EMAIL }, () => json(ACK, 202), { accepted: true }],
  ["reset without automatic login", "reset", "password-resets", completePasswordReset, { token: TOKEN, password: PASSWORD }, () => new Response(null, { status: 204 }), null]
]) {
  test(`${label}: fresh matching bootstrap, fixed POST, no provider dependency`, async (t) => {
    const calls = [];
    t.mock.method(globalThis, "fetch", async (url, init) => {
      calls.push({ url, init });
      return calls.length === 1 ? json(BOOTSTRAP) : success();
    });
    assert.deepEqual(await invoke(payload), expected);
    assert.deepEqual(calls.map(({ url }) => url), [`/api/v1/auth/bootstrap?action=${action}`, `/api/v1/auth/${endpoint}`]);
    assert.equal(calls[0].init.method, "GET");
    assert.equal(calls[0].init.body, undefined);
    assert.equal(calls[1].init.method, "POST");
    assert.deepEqual(JSON.parse(calls[1].init.body), payload);
    assert.equal(calls[1].init.headers["X-CSRF-Token"], BOOTSTRAP.csrf_token);
    for (const { init } of calls) {
      assert.equal(init.credentials, "same-origin");
      assert.equal(init.mode, "same-origin");
      assert.equal(init.cache, "no-store");
      assert.equal(init.redirect, "error");
      assert.equal(init.referrerPolicy, "no-referrer");
      assert.equal(init.headers.Origin, undefined);
      assert.equal(init.headers.Cookie, undefined);
    }
  });
}

test("403 causes no automatic retry; the next deliberate submit gets a new challenge", async (t) => {
  let bootstraps = 0;
  const posts = [];
  t.mock.method(globalThis, "fetch", async (url, init) => {
    if (url.includes("bootstrap")) return json({ ...BOOTSTRAP, csrf_token: `fresh-${++bootstraps}` });
    posts.push(init.headers["X-CSRF-Token"]);
    return posts.length === 1 ? json({ detail: "private-server" }, 403) : json(SESSION);
  });
  await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD }), expectError("challenge_expired", 403));
  assert.equal(bootstraps, 1);
  assert.equal(posts.length, 1);
  assert.deepEqual(await signInWithPassword({ email: EMAIL, password: PASSWORD }), SESSION);
  assert.deepEqual(posts, ["fresh-1", "fresh-2"]);
});

for (const [status, code] of [[400, "invalid_proof"], [401, "credentials_rejected"], [422, "invalid_input"], [503, "unavailable"]]) {
  test(`HTTP ${status} exposes only safe typed feedback and never replays`, async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async (url) => url.includes("bootstrap")
      ? json(BOOTSTRAP) : json({ detail: "private-server", password: PASSWORD, email: EMAIL, token: TOKEN }, status));
    await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD }), expectError(code, status));
    assert.equal(fetch.mock.callCount(), 2);
  });
}

test("disabled bootstrap stops before POST with a safe unavailable state", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => json({ detail: "private-server" }, 503));
  await assert.rejects(requestRegistration({ email: EMAIL }), expectError("unavailable", 503));
  assert.equal(fetch.mock.callCount(), 1);
});

for (const [header, expected] of [["60", 60], ["0", 0], ["999999999999", null], ["-1", null], ["private-server", null]]) {
  test(`429 Retry-After ${header} is bounded and never schedules a retry`, async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => json({ detail: "private-server" }, 429, { "Retry-After": header }));
    await assert.rejects(requestRegistration({ email: EMAIL }), (error) => {
      expectError("throttled", 429)(error);
      assert.equal(error.retryAfterSeconds, expected);
      return true;
    });
    assert.equal(fetch.mock.callCount(), 1);
  });
}

for (const body of [
  null, [], { ...BOOTSTRAP, csrf_token: "" }, { ...BOOTSTRAP, csrf_token: "a\r\nb" },
  { ...BOOTSTRAP, csrf_token: "a".repeat(513) },
  { ...BOOTSTRAP, capabilities: { ...BOOTSTRAP.capabilities, password_login: "yes" } },
  { ...BOOTSTRAP, capabilities: { ...BOOTSTRAP.capabilities, password_login: false } },
  { ...BOOTSTRAP, password_policy: { ...BOOTSTRAP.password_policy, minimum_length: 8 } }
]) {
  test(`malformed bootstrap ${JSON.stringify(body)?.slice(0, 70)} cannot authorize a POST`, async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => json(body));
    await assert.rejects(requestRegistration({ email: EMAIL }), expectError("invalid_response", 502));
    assert.equal(fetch.mock.callCount(), 1);
  });
}

test("unexpected success status or enumeration-bearing acknowledgement is not success", async (t) => {
  let result = json({ detail: "Account exists: private-server" }, 202);
  t.mock.method(globalThis, "fetch", async (url) => url.includes("bootstrap") ? json(BOOTSTRAP) : result);
  await assert.rejects(requestRegistration({ email: EMAIL }), expectError("invalid_response", 502));
  result = json(ACK, 200);
  await assert.rejects(requestRegistration({ email: EMAIL }), expectError("invalid_response", 502));
});

test("passwords preserve Unicode and leading/trailing spaces without client truncation", async (t) => {
  const password = "  Cafe\u0301 fixture \u{1F512} password  ";
  let sent;
  t.mock.method(globalThis, "fetch", async (url, init) => {
    if (url.includes("bootstrap")) return json(BOOTSTRAP);
    sent = JSON.parse(init.body);
    return json(SESSION);
  });
  await signInWithPassword({ email: EMAIL, password });
  assert.equal(sent.password, password);
});

test("input bounds and malformed proof reject before consuming network resources", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", () => { throw new Error("Unexpected network"); });
  for (const args of [undefined, { email: "" }, { email: "a".repeat(255) }, { email: "mail\r\n@example.test" }]) {
    await assert.rejects(requestRegistration(args), expectError("invalid_input", 422));
  }
  for (const password of ["", "a".repeat(513), "\u{1F512}".repeat(513), {}]) {
    await assert.rejects(signInWithPassword({ email: EMAIL, password }), expectError("invalid_input", 422));
  }
  for (const token of ["", "a".repeat(42), "a".repeat(44), "/".repeat(43), "../reset"]) {
    await assert.rejects(completePasswordReset({ token, password: PASSWORD }), expectError("invalid_proof", 400));
  }
  assert.equal(fetch.mock.callCount(), 0);
});

test("oversized declared responses are cancelled before parsing", async (t) => {
  let cancelled = false;
  const body = new ReadableStream({ cancel() { cancelled = true; } });
  t.mock.method(globalThis, "fetch", async () => new Response(body, {
    headers: { "Content-Type": "application/json", "Content-Length": "16385" }
  }));
  await assert.rejects(requestRegistration({ email: EMAIL }), expectError("invalid_response", 502));
  assert.equal(cancelled, true);
});

test("streaming byte bound applies even if Content-Length lies", async (t) => {
  let cancelled = false;
  const body = new ReadableStream({
    pull(controller) { controller.enqueue(new Uint8Array(1024)); },
    cancel() { cancelled = true; }
  });
  const fetch = t.mock.method(globalThis, "fetch", async () => new Response(body, {
    headers: { "Content-Type": "application/json", "Content-Length": "12" }
  }));
  await assert.rejects(requestRegistration({ email: EMAIL }), expectError("invalid_response", 502));
  assert.equal(cancelled, true);
  assert.equal(fetch.mock.callCount(), 1);
});

for (const make of [
  () => new Response("private-server", { headers: { "Content-Type": "text/html" } }),
  () => new Response("private-server", { headers: { "Content-Type": "application/json" } }),
  () => new Response(Uint8Array.from([0xff]), { headers: { "Content-Type": "application/json" } }),
  () => { const response = json(BOOTSTRAP); Object.defineProperty(response, "redirected", { value: true }); return response; }
]) {
  test("invalid JSON, encoding, media or redirect fails closed without reflecting content", async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => make());
    await assert.rejects(requestRegistration({ email: EMAIL }), expectError("invalid_response", 502));
    assert.equal(fetch.mock.callCount(), 1);
  });
}

test("network failure never exposes submitted input or repeats the POST", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("bootstrap")) return json(BOOTSTRAP);
    throw new TypeError(`private-server ${PASSWORD} ${TOKEN}`);
  });
  await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD }), expectError("unavailable", 503));
  assert.equal(fetch.mock.callCount(), 2);
});

test("abort before or during bootstrap prevents a POST and releases the action guard", async (t) => {
  const already = new AbortController();
  already.abort("private-server");
  const fetch = t.mock.method(globalThis, "fetch", async () => json(BOOTSTRAP));
  await assert.rejects(requestRegistration({ email: EMAIL, signal: already.signal }), { name: "AbortError" });
  assert.equal(fetch.mock.callCount(), 0);
  const current = new AbortController();
  fetch.mock.mockImplementation(async () => { current.abort(); return json(BOOTSTRAP); });
  await assert.rejects(requestRegistration({ email: EMAIL, signal: current.signal }), { name: "AbortError" });
  assert.equal(fetch.mock.callCount(), 1);
  fetch.mock.mockImplementation(async (url) => url.includes("bootstrap") ? json(BOOTSTRAP) : json(ACK, 202));
  assert.deepEqual(await requestRegistration({ email: EMAIL }), { accepted: true });
});

test("overlapping submissions are rejected, never coalesced or queued for replay", async (t) => {
  let release;
  const firstBootstrap = new Promise((resolve) => { release = resolve; });
  const fetch = t.mock.method(globalThis, "fetch", async (url) => url.includes("bootstrap") ? firstBootstrap : json(ACK, 202));
  const first = requestRegistration({ email: EMAIL });
  await assert.rejects(requestPasswordReset({ email: EMAIL }), expectError("busy", 409));
  assert.equal(fetch.mock.callCount(), 1);
  release(json(BOOTSTRAP));
  assert.deepEqual(await first, { accepted: true });
  assert.equal(fetch.mock.callCount(), 2);
});

test("an aborted POST never publishes a late session even if fetch resolves", async (t) => {
  const controller = new AbortController();
  const fetch = t.mock.method(globalThis, "fetch", async (url) => {
    if (url.includes("bootstrap")) return json(BOOTSTRAP);
    controller.abort();
    return json(SESSION);
  });
  await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD, signal: controller.signal }), { name: "AbortError" });
  assert.equal(fetch.mock.callCount(), 2);
});

test("the total deadline aborts a stalled request without retry", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const fetch = t.mock.method(globalThis, "fetch", (_url, { signal }) => new Promise((_resolve, reject) => {
    signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
  }));
  const result = assert.rejects(requestRegistration({ email: EMAIL }), expectError("unavailable", 503));
  t.mock.timers.tick(30000);
  await result;
  assert.equal(fetch.mock.callCount(), 1);
});

test("canonical login envelope is validated before exposing account state", async (t) => {
  let session = { ...SESSION, user: { ...SESSION.user, id: "foreign/provider/subject" } };
  t.mock.method(globalThis, "fetch", async (url) => url.includes("bootstrap") ? json(BOOTSTRAP) : json(session));
  await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD }), expectError("invalid_response", 502));
  session = { ...SESSION, can_query: "true" };
  await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD }), expectError("invalid_response", 502));
  session = { ...SESSION, user: { ...SESSION.user, name: "a".repeat(257) } };
  await assert.rejects(signInWithPassword({ email: EMAIL, password: PASSWORD }), expectError("invalid_response", 502));
});

test("optional Google-config capabilities stay explicit booleans, not permission grants", async (t) => {
  const capabilities = { google_login: true, password_login: false, durable_sessions: true };
  const base = { client_id: "fixture.apps.googleusercontent.com", nonce: "fixture", csrf_token: "fixture" };
  let body = { ...base, capabilities };
  t.mock.method(globalThis, "fetch", async () => json(body));
  assert.deepEqual((await fetchAuthConfig()).capabilities, capabilities);
  body = { ...base, capabilities: JSON.parse('{"__proto__":true}') };
  await assert.rejects(fetchAuthConfig(), (error) => error.status === 502);
  assert.throws(() => sessionResponse({ ...SESSION, capabilities: { constructor: true } }), (error) => error.status === 502);
});
