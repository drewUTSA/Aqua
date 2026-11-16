import assert from "node:assert/strict";
import test from "node:test";
import { askCompanionHelp, getCompanionCapabilities, prepareCompanionDraft, companionAnswer, companionCapabilities } from "../src/services/companionClient.js";
import { workspaceRequest } from "../src/services/workspaceClient.js";
import { activateSession, clearHistory } from "../src/services/historyAuthority.js";

const hash = "a".repeat(64);
const menu = { schemaVersion: 1, advisory: true, selection: "explicit", pack_revision: hash,
  capabilities: [{ id: "app_help", behavior: "reviewed_lookup" }, { id: "authorized_question", behavior: "seed_draft" }] };
const answer = { schemaVersion: 1, status: "answered", capability_id: "app_help", method: "reviewed_lookup",
  message: "Use the reviewed help.", citations: [{ id: "overview", title: "What Aqua does", revision: hash }], pack_revision: hash };
const json = (value, headers = {}) => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json", ...headers } });

test("help uses fixed same-origin private routes and explicit choice never submits analysis", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json(init.method === "POST" ? answer : menu); });
  const choices = await getCompanionCapabilities();
  assert.equal(prepareCompanionDraft("Count loans", choices), "Count loans");
  assert.equal(calls.length, 1);
  assert.equal((await askCompanionHelp("How does Aqua work?", { csrfToken: "csrf" })).method, "reviewed_lookup");
  assert.deepEqual(calls.map((value) => value.url), ["/api/v1/companion/capabilities", "/api/v1/companion/help"]);
  assert.deepEqual(JSON.parse(calls[1].init.body), { schemaVersion: 1, question: "How does Aqua work?" });
  for (const { init } of calls) { assert.equal(init.credentials, "same-origin"); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error"); }
  assert.equal(calls[1].init.headers["X-CSRF-Token"], "csrf");
});

test("only the closed advisory tool set and source-bound help answers are accepted", () => {
  for (const capabilities of ([{ id: "monthly_trend", behavior: "execute" }], [...menu.capabilities, menu.capabilities[0]], [{ id: "authorized_question", behavior: "seed_draft" }])) {
    assert.throws(() => companionCapabilities({ ...menu, capabilities }), { code: "invalid_response" });
  }
  assert.throws(() => prepareCompanionDraft("Count loans", { ...menu, capabilities: [menu.capabilities[0]] }), { code: "forbidden" });
  for (const patch of [{ method: "llm" }, { citations: [] }, { sql: "SELECT 1" }, { citations: [{ ...answer.citations[0], revision: "b".repeat(64) }] }, { status: "abstained" }]) {
    assert.throws(() => companionAnswer({ ...answer, ...patch }), { code: "invalid_response" });
  }
  assert.equal(companionAnswer({ ...answer, status: "abstained", citations: [] }).status, "abstained");
});

test("help validates questions before network and never automatically retries a failure", async (t) => {
  const calls = t.mock.method(globalThis, "fetch", async () => { throw new Error("private provider body"); });
  for (const question of ["", " ", "x".repeat(2001), "bad\0value", "\ud800"]) {
    await assert.rejects(askCompanionHelp(question, { csrfToken: "csrf" }), { code: "invalid_input" });
  }
  await assert.rejects(askCompanionHelp("charts"), { code: "unauthenticated" });
  assert.equal(calls.mock.callCount(), 0);
  await assert.rejects(askCompanionHelp("charts", { csrfToken: "csrf" }), (error) => !error.message.includes("private"));
  assert.equal(calls.mock.callCount(), 1);
});

test("companion rejects oversized Content-Length before reading or retaining its stream", async (t) => {
  let cancelled = false, pulls = 0;
  const body = new ReadableStream({ pull() { pulls += 1; }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  t.mock.method(globalThis, "fetch", async () => new Response(body, { headers: { "Content-Type": "application/json", "Content-Length": "32769" } }));
  await assert.rejects(getCompanionCapabilities(), { code: "invalid_response" });
  assert.equal(pulls, 0); assert.equal(cancelled, true);
});

test("companion cancels an oversized chunked body using the early 32KiB cap", async (t) => {
  let cancelled = false;
  const body = new ReadableStream({ pull(controller) { controller.enqueue(new Uint8Array(32769)); }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  t.mock.method(globalThis, "fetch", async () => new Response(body, { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(getCompanionCapabilities(), { code: "invalid_response" });
  assert.equal(cancelled, true);
});

test("optional workspace byte cap is validated and existing callers retain the original default", async (t) => {
  const calls = t.mock.method(globalThis, "fetch", async () => json({ text: "x".repeat(40000) }));
  for (const maxBytes of [0, -1, 1.5, "32768", NaN, 6 * 1024 * 1024 + 1]) {
    await assert.rejects(workspaceRequest("/fixture", { maxBytes }), { code: "invalid_input" });
  }
  assert.equal(calls.mock.callCount(), 0);
  assert.equal((await workspaceRequest("/fixture")).text.length, 40000);
  await assert.rejects(workspaceRequest("/fixture", { maxBytes: 32768 }), { code: "invalid_response" });
});

test("late help responses cannot cross an account change", async (t) => {
  clearHistory();
  activateSession({ user: { id: "10000000-0000-4000-8000-000000000001" }, csrf_token: "csrf-a" });
  let release;
  t.mock.method(globalThis, "fetch", () => new Promise((resolve) => { release = resolve; }));
  const pending = askCompanionHelp("charts", { csrfToken: "csrf-a" });
  activateSession({ user: { id: "20000000-0000-4000-8000-000000000002" }, csrf_token: "csrf-b" });
  release(json(answer));
  await assert.rejects(pending, { name: "AbortError" });
  clearHistory();
});

test("explicitly aborted help cannot update state", async (t) => {
  const controller = new AbortController(); controller.abort();
  const calls = t.mock.method(globalThis, "fetch", async () => json(answer));
  await assert.rejects(askCompanionHelp("charts", { csrfToken: "csrf", signal: controller.signal }), { name: "AbortError" });
  assert.equal(calls.mock.callCount(), 0);
});
