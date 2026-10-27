import assert from "node:assert/strict";
import test from "node:test";
import { getAnalysis, cancelAnalysis, watchAnalysis } from "../src/services/analysisClient.js";
import { analysisEvent, analysisSnapshot, eventParser } from "../src/services/analysisProtocol.js";
import { messageRecord } from "../src/services/workspaceContract.js";
import { REQUEST, CHAT, snapshot, event, frame, json } from "./analysis-fixture.mjs";

test("status GET and explicit cancel use owned UUID routes and an empty CSRF protected body", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json(snapshot(), init.method === "POST" ? 202 : 200); });
  assert.equal((await getAnalysis(REQUEST)).request.stage, "generating"); await cancelAnalysis(REQUEST, { csrfToken: "csrf" });
  assert.deepEqual(calls.map(({ url }) => url), [`/api/v1/analysis-requests/${REQUEST}`, `/api/v1/analysis-requests/${REQUEST}/cancel`]);
  assert.equal(calls[0].init.method, "GET"); assert.equal(calls[0].init.body, undefined); assert.equal(calls[0].init.headers["X-CSRF-Token"], undefined);
  assert.equal(calls[1].init.method, "POST"); assert.equal(calls[1].init.body, "{}"); assert.equal(calls[1].init.headers["X-CSRF-Token"], "csrf");
  for (const { init } of calls) { assert.equal(init.credentials, "same-origin"); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error"); assert.equal(init.referrerPolicy, "no-referrer"); }
});

test("malformed UUIDs or missing CSRF never reach the network", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("must not fetch"); });
  await assert.rejects(getAnalysis("//foreign.invalid/secret"), { code: "invalid_input" });
  await assert.rejects(cancelAnalysis(REQUEST), { status: 401 }); assert.equal(fetch.mock.callCount(), 0);
  await assert.rejects(watchAnalysis(REQUEST, { sequence: "PRIVATE\r\nInjected" }), { code: "invalid_input" }); assert.equal(fetch.mock.callCount(), 0);
});

test("snapshots require matching request, canonical messages and typed lifecycle metadata", () => {
  assert.equal(analysisSnapshot(snapshot(), REQUEST).assistant.response.status, "loading");
  assert.equal(messageRecord(snapshot("cancelled", "cancelled").assistant_message).response.error.message, "This analysis was cancelled on the server.");
  for (const state of ["cancelled", "interrupted", "expired"]) assert.equal(messageRecord(snapshot(state, state).assistant_message).response.error.retryable, true);
  const migrated = snapshot("complete", "complete", 1, 0); migrated.request.deadline_at = null;
  assert.equal(analysisSnapshot(migrated, REQUEST).request.deadlineAt, null);
  for (const value of [{ ...snapshot(), request: { ...snapshot().request, id: CHAT } }, { ...snapshot(), request: { ...snapshot().request, version: 0 } },
    { ...snapshot(), request: { ...snapshot().request, stage: "PRIVATE_REASONING" } }, { ...snapshot(), request: { ...snapshot().request, deadline_at: null } },
    { ...snapshot(), request: { ...snapshot().request, last_event_sequence: -1 } }]) assert.throws(() => analysisSnapshot(value, REQUEST), /workspace_invalid_response/);
});

test("metadata parser accepts split CRLF and comments without exposing content", () => {
  const received = [], consume = eventParser(REQUEST, (value) => received.push(value));
  const data = ": heartbeat\r\n" + frame(event()).replaceAll("\n", "\r\n") + frame(event("running", "executing", 3, 2), "snapshot-required");
  for (const character of data) consume(character);
  consume(frame(event("complete", "complete", 4, 3)).slice(0, -1)); // EOF without the final blank line never dispatches.
  assert.deepEqual(received.map(({ sequence, stage, snapshotRequired }) => [sequence, stage, snapshotRequired]), [[1, "generating", false], [2, "executing", true]]);
  assert.equal(JSON.stringify(received).includes("heartbeat"), false);
});

test("unknown/sensitive fields, bad state/sequence and wrong event IDs fail with fixed diagnostics", () => {
  const invalid = [{ ...event(), sql: "PRIVATE_SQL" }, { ...event(), question: "PRIVATE_PROMPT" }, { ...event(), sequence: -1 }, { ...event(), version: 1.5 },
    { ...event(), request_id: CHAT }, { ...event(), state: "complete", stage: "generating" }];
  for (const value of invalid) assert.throws(() => analysisEvent("progress", `${REQUEST}:${value.sequence}`, JSON.stringify(value), REQUEST), /workspace_invalid_response/);
  assert.throws(() => analysisEvent("progress", `${REQUEST}:9`, JSON.stringify(event()), REQUEST), /workspace_invalid_response/);
  assert.throws(() => analysisEvent("tokens", `${REQUEST}:1`, JSON.stringify(event()), REQUEST), /workspace_invalid_response/);
  assert.throws(() => analysisEvent("progress", `${REQUEST}:1`, "{PRIVATE_PROMPT", REQUEST), (error) => !error.message.includes("PRIVATE"));
});

test("SSE frames are bounded in UTF8 bytes, not character count", () => {
  const consume = eventParser(REQUEST, () => assert.fail("oversized frame cannot dispatch"));
  assert.throws(() => consume(`: ${"😀".repeat(2050)}`), /workspace_invalid_response/);
});

test("genuine chunked stream delivers metadata before closure and reconnects with a safe Last-Event-ID", async (t) => {
  let controller, init, opened = false; const received = [], encoder = new TextEncoder();
  t.mock.method(globalThis, "fetch", async (url, options) => { assert.equal(url, `/api/v1/analysis-requests/${REQUEST}/events`); init = options;
    return new Response(new ReadableStream({ start(value) { controller = value; } }), { headers: { "Content-Type": "text/event-stream; charset=utf-8" } }); });
  const pending = watchAnalysis(REQUEST, { sequence: 3, onOpen: () => { opened = true; }, onEvent: (value) => received.push(value) });
  await new Promise((resolve) => setImmediate(resolve)); assert.equal(opened, true);
  const bytes = encoder.encode(": ☃\n" + frame(event("running", "executing", 4, 4)));
  for (let index = 0; index < bytes.length; index += 2) controller.enqueue(bytes.slice(index, index + 2));
  await new Promise((resolve) => setImmediate(resolve)); assert.equal(received.length, 1); assert.equal(received[0].stage, "executing");
  assert.equal(init.method, "GET"); assert.equal(init.headers["Last-Event-ID"], `${REQUEST}:3`); assert.equal(init.body, undefined);
  controller.close(); await pending;
});

for (const [label, bytes] of [["invalid UTF8", Uint8Array.of(0xff)], ["oversized total stream", new TextEncoder().encode((": heartbeat\n\n").repeat(21000))]]) {
  test(`stream rejects ${label} with a fixed safe error`, async (t) => {
    t.mock.method(globalThis, "fetch", async () => new Response(new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }), { headers: { "Content-Type": "text/event-stream" } }));
    await assert.rejects(watchAnalysis(REQUEST, { onEvent() {} }), { code: "invalid_response" });
  });
}

test("stream rejects sensitive malformed data and reports authorization without server text", async (t) => {
  t.mock.method(globalThis, "fetch", async () => new Response(`event: progress\nid: ${REQUEST}:1\ndata: {PRIVATE_SECRET\n\n`, { headers: { "Content-Type": "text/event-stream" } }));
  await assert.rejects(watchAnalysis(REQUEST, { onEvent() {} }), (error) => error.code === "invalid_response" && !error.message.includes("PRIVATE"));
  t.mock.method(globalThis, "fetch", async () => json({ error: "PRIVATE_SECRET" }, 403));
  await assert.rejects(watchAnalysis(REQUEST, { onEvent() {} }), (error) => error.status === 403 && !error.message.includes("PRIVATE"));
});

test("external abort ends observation without enqueueing or cancelling a server request", async (t) => {
  const controller = new AbortController(); let count = 0;
  t.mock.method(globalThis, "fetch", async (_url, options) => { count++; return new Response(new ReadableStream({ start(stream) {
    options.signal.addEventListener("abort", () => stream.error(new DOMException("PRIVATE", "AbortError")), { once: true });
  } }), { headers: { "Content-Type": "text/event-stream" } }); });
  const pending = watchAnalysis(REQUEST, { signal: controller.signal, onEvent: () => assert.fail("late event") });
  await new Promise((resolve) => setImmediate(resolve)); controller.abort(); await assert.rejects(pending, { name: "AbortError" }); assert.equal(count, 1);
});

test("a silent stream has a fixed 65-second read lifetime and is closed before fallback", async (t) => {
  let expire, cancelled = false;
  t.mock.method(globalThis, "setTimeout", (callback, milliseconds) => { assert.equal(milliseconds, 65000); expire = callback; return 0; });
  t.mock.method(globalThis, "fetch", async (_url, { signal }) => new Response(new ReadableStream({ start(stream) {
    signal.addEventListener("abort", () => { cancelled = true; stream.error(new DOMException("PRIVATE", "AbortError")); }, { once: true });
  } }), { headers: { "Content-Type": "text/event-stream" } }));
  const pending = watchAnalysis(REQUEST, { onEvent: () => assert.fail("no event") }); await new Promise((resolve) => setImmediate(resolve)); expire();
  await assert.rejects(pending, { code: "invalid_response" }); assert.equal(cancelled, true);
});
