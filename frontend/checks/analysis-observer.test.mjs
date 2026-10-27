import assert from "node:assert/strict";
import test from "node:test";
import { observeAnalysis } from "../src/services/analysisObserver.js";
import { analysisSnapshot } from "../src/services/analysisProtocol.js";
import { WorkspaceError } from "../src/services/workspaceClient.js";
import { REQUEST, snapshot } from "./analysis-fixture.mjs";

const saved = (...args) => analysisSnapshot(snapshot(...args), REQUEST);
const metadata = (state, stage, version, sequence, extra = {}) => ({ requestId: REQUEST, state, stage, version, sequence, snapshotRequired: false, ...extra });
const aborted = () => new DOMException("stopped", "AbortError");

test("terminal event reconciles an authoritative snapshot and never fabricates a completed result", async () => {
  const controller = new AbortController(), states = [], progress = []; let reads = 0, clock = 0;
  await observeAnalysis(REQUEST, { signal: controller.signal, now: () => clock, pause: async (ms) => { clock += ms; },
    read: async () => ++reads === 1 ? saved("running", "generating", 2, 1) : saved("complete", "complete", 4, 3),
    watch: async (_id, { onEvent, signal }) => {
      onEvent(metadata("running", "executing", 3, 2));
      assert.deepEqual(states, ["running"]);
      onEvent(metadata("complete", "complete", 4, 3));
      assert.deepEqual(states, ["running"]); // metadata cannot carry or confirm a final result.
      await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true })); throw aborted();
    }, onSnapshot: (value) => states.push(value.request.state), onProgress: (value) => progress.push(value.stage), onConnection() {} });
  assert.deepEqual(states, ["running", "complete"]); assert.deepEqual(progress, ["executing"]); assert.equal(reads, 2);
});

test("duplicates/out-of-order metadata are ignored and a gap triggers one bounded snapshot reconciliation", async () => {
  const progress = [], versions = []; let reads = 0, watches = 0;
  await observeAnalysis(REQUEST, { signal: new AbortController().signal,
    read: async () => ++reads === 1 ? saved() : saved("complete", "complete", 9, 8),
    watch: async (_id, { onEvent, signal }) => { watches++;
      onEvent(metadata("running", "schema", 1, 0)); onEvent(metadata("running", "generating", 2, 1));
      onEvent(metadata("running", "executing", 3, 2));
      for (let index = 0; index < 100; index++) onEvent(metadata("running", "persisting", 8, 7));
      await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true })); throw aborted();
    }, onProgress: (value) => progress.push(value.sequence), onSnapshot: (value) => versions.push(value.request.version), onConnection() {} });
  assert.deepEqual(progress, [2]); assert.deepEqual(versions, [2, 9]); assert.equal(reads, 2); assert.equal(watches, 1);
});

test("SSE failure falls back to status GETs with no replay or server cancellation", async () => {
  const connections = [], states = [], delays = []; let reads = 0, streams = 0, clock = 0;
  await observeAnalysis(REQUEST, { signal: new AbortController().signal, now: () => clock, pause: async (ms) => { delays.push(ms); clock += ms; },
    read: async () => ++reads < 3 ? saved("running", "executing", reads + 1, reads) : saved("complete", "complete", 5, 4),
    watch: async () => { streams++; throw new WorkspaceError("unavailable", 503); },
    onSnapshot: (value) => states.push(value.request.state), onProgress: () => assert.fail("no metadata"), onConnection: (value) => connections.push(value) });
  assert.deepEqual(states, ["running", "running", "complete"]); assert.equal(streams, 1); assert.equal(reads, 3); assert.deepEqual(delays, [2000, 2000]);
  assert.equal(connections.includes("polling"), true);
});

test("cancelling stays nonterminal until a fresh saved cancelled snapshot", async () => {
  const states = []; let reads = 0, clock = 0;
  await observeAnalysis(REQUEST, { signal: new AbortController().signal, now: () => clock, pause: async (ms) => { clock += ms; },
    read: async () => ++reads < 3 ? saved("cancelling", "cancelling", 4, 3) : saved("cancelled", "cancelled", 5, 4),
    watch: async () => { throw new WorkspaceError("unavailable", 503); }, onSnapshot: (value) => states.push(value.request.state), onProgress() {}, onConnection() {} });
  assert.deepEqual(states, ["cancelling", "cancelling", "cancelled"]);
});

for (const status of [401, 403, 404]) test(`status ${status} ends observation without continuing a stream or polling`, async () => {
  let reads = 0, streams = 0;
  await assert.rejects(observeAnalysis(REQUEST, { signal: new AbortController().signal,
    read: async () => { reads++; throw new WorkspaceError("forbidden", status); }, watch: async () => { streams++; },
    onSnapshot: () => assert.fail("no authorized snapshot"), onProgress() {}, onConnection() {} }), { status });
  assert.equal(reads, 1); assert.equal(streams, 0);
});

test("aborted late GET cannot commit or enqueue a replacement request", async () => {
  const controller = new AbortController(); let release, reads = 0;
  const held = new Promise((resolve) => { release = resolve; });
  const operation = observeAnalysis(REQUEST, { signal: controller.signal, read: async () => { reads++; await held; return saved(); },
    watch: async () => assert.fail("no stream after abort"), onSnapshot: () => assert.fail("no late commit"), onProgress() {}, onConnection() {} });
  controller.abort(); release(); await assert.rejects(operation, { name: "AbortError" }); assert.equal(reads, 1);
});

test("poll errors back off and terminate after six failures", async () => {
  let reads = 0, clock = 0; const delays = [];
  await assert.rejects(observeAnalysis(REQUEST, { signal: new AbortController().signal, now: () => clock,
    pause: async (ms) => { clock += ms; delays.push(ms); }, read: async () => { if (++reads === 1) return saved(); throw new WorkspaceError("unavailable"); },
    watch: async () => { throw new WorkspaceError("unavailable", 503); }, onSnapshot() {}, onProgress() {}, onConnection() {} }), { code: "unavailable" });
  assert.equal(reads, 7); assert.deepEqual(delays, [2000, 4000, 8000, 15000, 15000, 15000]);
});

test("observer lifetime stays bounded even when a server keeps reporting a nonterminal job", async () => {
  let reads = 0, clock = 0;
  await assert.rejects(observeAnalysis(REQUEST, { signal: new AbortController().signal, now: () => clock,
    pause: async () => { clock += 300001; }, read: async () => { reads++; return saved(); }, watch: async () => { throw new WorkspaceError("unavailable", 503); },
    onSnapshot() {}, onProgress() {}, onConnection() {} }), { code: "unavailable" });
  assert.ok(reads <= 3);
});

test("stream closure after session revocation fails the fresh GET before polling or exposing a result", async () => {
  let reads = 0, streams = 0; const states = [];
  await assert.rejects(observeAnalysis(REQUEST, { signal: new AbortController().signal,
    read: async () => { if (++reads === 1) return saved(); throw new WorkspaceError("unauthenticated", 401); },
    watch: async () => { streams++; }, pause: async () => assert.fail("no polling after revoked session"),
    onSnapshot: (value) => states.push(value.request.state), onProgress() {}, onConnection() {} }), { status: 401 });
  assert.equal(reads, 2); assert.equal(streams, 1); assert.deepEqual(states, ["running"]);
});

test("terminal metadata cannot bypass a newly revoked data grant at the fresh snapshot boundary", async () => {
  let reads = 0; const states = [];
  await assert.rejects(observeAnalysis(REQUEST, { signal: new AbortController().signal,
    read: async () => { if (++reads === 1) return saved(); throw new WorkspaceError("forbidden", 403); },
    watch: async (_id, { onEvent, signal }) => { onEvent(metadata("complete", "complete", 3, 2));
      await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true })); throw aborted(); },
    onSnapshot: (value) => states.push(value.request.state), onProgress() {}, onConnection() {} }), { status: 403 });
  assert.equal(reads, 2); assert.deepEqual(states, ["running"]);
});

test("a bounded stream reconnect resumes the latest sequence instead of starting a new operation", async () => {
  let reads = 0, streams = 0, clock = 0; const cursors = [];
  await observeAnalysis(REQUEST, { signal: new AbortController().signal, now: () => clock, pause: async (ms) => { clock += ms; },
    read: async () => ++reads === 1 ? saved() : reads === 2 ? saved("running", "executing", 3, 2) : saved("complete", "complete", 4, 3),
    watch: async (_id, { sequence, onEvent, signal }) => { cursors.push(sequence);
      if (++streams === 1) { onEvent(metadata("running", "executing", 3, 2)); return; }
      onEvent(metadata("complete", "complete", 4, 3)); await new Promise((resolve) => signal.addEventListener("abort", resolve, { once: true })); throw aborted(); },
    onSnapshot() {}, onProgress() {}, onConnection() {} });
  assert.deepEqual(cursors, [1, 2]); assert.equal(reads, 3); assert.equal(streams, 2);
});
