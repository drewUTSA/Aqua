import assert from "node:assert/strict";
import test from "node:test";
import { NotesResponseGate, notesRealMode, requireNotesReady, notesResponsePrivate, notesCleanupConfirmed, notesStats, notesRealKey, notesForgetConfirmed,
  REAL_NOTES_GOLD, REAL_NOTES_CASES, NotesCancellationEvidence, notesCancellationCleanupConfirmed } from "./context-notes-real-browser-checks.mjs";

const origin = "http://127.0.0.1:54321", id = "58000000-0000-4000-8000-000000000001", owner = "58000000-0000-4000-8000-000000000002", scope = "a".repeat(64);
const request = () => ({ method: "POST", url: `${origin}/api/v1/me/context-notes/${id}/prepare`, postData: JSON.stringify({ schemaVersion: 1, expected_scope_id: scope, revision: 2 }) });
const response = () => ({ status: 200, bodyBase64: Buffer.from(JSON.stringify({ schemaVersion: 1, owner_id: owner, scope: { id: scope, can_use: true }, unverified: true, execution_enabled: false,
  source: { id, revision: 2, kind: "note", label: REAL_NOTES_GOLD.label }, draft: REAL_NOTES_GOLD.body, requires_review: true })).toString("base64") });
function setup() {
  let time = 0, sequence = 0; const timers = new Map();
  const gate = new NotesResponseGate({ origin, now: () => time, setTimer: (fn, milliseconds) => { const key = ++sequence; timers.set(key, { fn, until: time + milliseconds }); return key; }, clearTimer: key => timers.delete(key) });
  const advance = value => { time = value; for (const [key, timer] of [...timers]) if (timer.until <= time) { timers.delete(key); timer.fn(); } };
  return { gate, timers, advance, clockOnly: value => { time = value; } };
}
const ready = () => ({ notes_fixture: true, schema_version: 10, workspace_analysis_fixture: false, bank_demo_fixture: false, dataset_grants: 0,
  max_requests: 256, max_seconds: 300, body_bytes_max: 16384, origin, network: "none", database_transport: "private_unix_socket", capabilities: { workspace_analysis: false } });

test("forget waits for confirmed removal of the selected note before the next keyboard action", () => {
  const stale = `[data-notes-select="${id}"], [data-notes-forget-confirm], [data-notes-body]`;
  const panel = (status, visible) => ({
    querySelector(selector) {
      if (selector === "[role=status]") return status ? { textContent: status } : null;
      assert.equal(selector, stale);
      return visible ? {} : null;
    }
  });
  const confirmed = "Forgot this library entry. Copies already sent in chat history are unchanged.";
  assert.equal(notesForgetConfirmed(null, id), false);
  assert.equal(notesForgetConfirmed(panel("Forgetting the saved library entry…", true), id), false);
  assert.equal(notesForgetConfirmed(panel(null, false), id), false);
  assert.equal(notesForgetConfirmed(panel(confirmed, true), id), false);
  assert.equal(notesForgetConfirmed(panel(confirmed, false), id), true);
});

test("notes mode is closed, exactly boolean, exclusive with analysis/bank and default-off", () => {
  assert.equal(notesRealMode(null, false), false); assert.equal(notesRealMode("bank-demo", false, true), false); assert.equal(notesRealMode("context-notes", false), true);
  for (const args of [[undefined, false], ["other", false], ["context-notes", true], ["context-notes", false, true], ["context-notes", 0], ["context-notes", "false"], ["context-notes", false, 0], [null, null]])
    assert.throws(() => notesRealMode(...args), /real_notes_fixture_mode_invalid/);
});

test("notes readiness requires exact current schema and every explicit nonanalysis boundary", () => {
  assert.equal(requireNotesReady(ready(), origin), true);
  for (const [key, value] of [["schema_version", 9], ["schema_version", 11], ["schema_version", true], ["schema_version", "10"], ["notes_fixture", 1],
    ["workspace_analysis_fixture", true], ["bank_demo_fixture", true], ["dataset_grants", 1], ["max_requests", 400], ["max_seconds", 301], ["body_bytes_max", 32768],
    ["origin", "http://127.0.0.1:54322"], ["network", "bridge"], ["database_transport", "tcp"], ["capabilities", { workspace_analysis: true }]])
    assert.throws(() => requireNotesReady({ ...ready(), [key]: value }, origin));
  for (const key of Object.keys(ready())) { const value = ready(); delete value[key]; assert.throws(() => requireNotesReady(value, origin)); }
  const poisoned = Object.defineProperty(ready(), "bank_demo_fixture", { get() { throw Error("getter evaluated"); } });
  assert.throws(() => requireNotesReady(poisoned, origin), /real_notes_record_invalid/);
});

test("gate accepts only an exact loopback origin and callable clock/timer dependencies", () => {
  for (const value of ["https://aqua-ai.us", "http://127.0.0.1:80", "http://localhost:54321", origin + "/", origin + "?x", "http://user@127.0.0.1:54321"])
    assert.throws(() => new NotesResponseGate({ origin: value }));
  for (const key of ["now", "setTimer", "clearTimer"]) assert.throws(() => new NotesResponseGate({ origin, [key]: 1 }));
});

test("an unarmed gate delegates without reading any response accessor", () => {
  const { gate } = setup(); const poisoned = Object.defineProperty({}, "bodyBase64", { get() { throw Error("getter"); } });
  assert.equal(gate.capture({}, poisoned, null), false); gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), true);
});

test("four source-bound computed responses finish once, clear timers, and exhaust the finite capture allowance", async () => {
  const { gate, timers } = setup(); let finishes = 0;
  for (let i = 0; i < 4; i++) { gate.arm(id, 2); assert.equal(gate.capture(request(), response(), async () => { finishes++; return { kind: "fulfilled" }; }), true); await gate.release(); }
  assert.equal(finishes, 4); assert.equal(timers.size, 0); assert.throws(() => gate.arm(id, 2), /real_notes_hold_capacity/);
  gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), true); assert.equal(gate.snapshot().released, 4);
});

test("an armed or outstanding slot cannot be replaced and unrelated requests do not consume the slot", async () => {
  const { gate } = setup(); gate.arm(id, 2); assert.throws(() => gate.arm(id, 2), /real_notes_hold_capacity/);
  assert.equal(gate.capture({ method: "GET" }, {}, null), false);
  assert.equal(gate.capture({ method: "POST", url: origin + "/api/auth/logout" }, {}, null), false);
  assert.equal(gate.capture(request(), response(), async () => ({ kind: "fulfilled" })), true); assert.throws(() => gate.arm(id, 2), /real_notes_hold_capacity/);
  await gate.release(); gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), true);
});

test("malformed source IDs and revision types cannot arm the gate", () => {
  const { gate } = setup();
  for (const pair of [[[id], 2], [id, true], [id, 0], [id, 1.5], [id, Number.MAX_SAFE_INTEGER + 1], ["not-a-uuid", 2]]) assert.throws(() => gate.arm(...pair), /real_notes_hold_source_invalid/);
  gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), true);
});

test("a getter is rejected without invoking it, leaving a failed abandoned slot", () => {
  const { gate } = setup(); gate.arm(id, 2); let getters = 0;
  const value = Object.defineProperty(response(), "bodyBase64", { get() { getters++; return ""; } });
  assert.throws(() => gate.capture(request(), value, async () => ({ kind: "fulfilled" })), /real_notes_hold_response_invalid/);
  assert.equal(getters, 0); assert.equal(gate.snapshot().abandoned, 1); gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), false);
});

test("origin/query/path traversal and noncanonical source URLs fail closed before capture", () => {
  for (const url of [request().url + "?owner=x", request().url + "#fragment", request().url.replace("127.0.0.1", "localhost"),
    origin + `/x/../api/v1/me/context-notes/${id}/prepare`, request().url.replace(id, "58000000-0000-4000-8000-000000000009")]) {
    const { gate } = setup(); gate.arm(id, 2); assert.throws(() => gate.capture({ ...request(), url }, response(), async () => ({ kind: "fulfilled" })));
    assert.equal(gate.snapshot().captured, 0); assert.equal(gate.snapshot().failed, true); gate.close();
  }
});

test("non200, malformed/noncanonical/oversized base64, invalid UTF8 and unbound DTOs cannot become held success", () => {
  const changes = [{ status: 409 }, { bodyBase64: "a" }, { bodyBase64: "====" }, { bodyBase64: "Zg" }, { bodyBase64: Buffer.alloc(16385).toString("base64") },
    { bodyBase64: Buffer.from([0xff]).toString("base64") }, { bodyBase64: Buffer.from("{broken").toString("base64") }];
  const original = JSON.parse(Buffer.from(response().bodyBase64, "base64"));
  for (const change of [{ requires_review: false }, { execution_enabled: true }, { schemaVersion: true }, { scope: { id: scope, can_use: false } },
    { source: { ...original.source, revision: 1 } }, { source: { ...original.source, id: owner } }, { rows: [] }])
    changes.push({ bodyBase64: Buffer.from(JSON.stringify({ ...original, ...change })).toString("base64") });
  for (const change of changes) { const { gate } = setup(); gate.arm(id, 2); assert.throws(() => gate.capture(request(), { ...response(), ...change }, async () => ({ kind: "fulfilled" }))); gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), false); }
});

test("a request must carry its captured revision and exact closed body snapshot", () => {
  for (const postData of ["{broken", JSON.stringify({ schemaVersion: 1, expected_scope_id: scope, revision: 1 }),
    JSON.stringify({ schemaVersion: 1, expected_scope_id: scope, revision: true }), JSON.stringify({ schemaVersion: 1, expected_scope_id: scope, revision: 2, owner_id: owner }), "x".repeat(8193)]) {
    const { gate } = setup(); gate.arm(id, 2); assert.throws(() => gate.capture({ ...request(), postData }, response(), async () => ({ kind: "fulfilled" }))); gate.close();
  }
});

test("expiration abandons a captured response, never calls finish and never counts a release", async () => {
  const { gate, advance, timers } = setup(); let finishes = 0;
  gate.arm(id, 2); gate.capture(request(), response(), () => { finishes++; }); advance(4000);
  await assert.rejects(gate.release(), /real_notes_held_response_deadline/); assert.equal(finishes, 0); assert.equal(timers.size, 0);
  assert.equal(gate.snapshot().released, 0); assert.equal(gate.snapshot().abandoned, 1); gate.close();
});

test("the exact lease boundary and rollback fail even when a delayed timer has not fired", async () => {
  for (const time of [4000, -1, NaN, Infinity]) {
    const { gate, clockOnly } = setup(); gate.arm(id, 2); gate.capture(request(), response(), async () => ({ kind: "fulfilled" })); clockOnly(time);
    await assert.rejects(gate.release()); assert.equal(gate.snapshot().released, 0); gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), false);
  }
});

test("finish rejection or completion after lease is red and is not counted as a successful release", async () => {
  for (const delayed of [false, true]) {
    const { gate, clockOnly } = setup(); gate.arm(id, 2); gate.capture(request(), response(), async () => { if (delayed) clockOnly(4000); else throw Error("synthetic_finish_failure"); });
    await assert.rejects(gate.release(), /real_notes_release_failed/); assert.equal(gate.snapshot().released, 0); assert.equal(gate.snapshot().abandoned, 1); gate.close();
  }
});

test("an unfinished callback remains inside the lease timer and rejects when it expires", async () => {
  const { gate, advance, timers } = setup(); gate.arm(id, 2); gate.capture(request(), response(), () => new Promise(() => {}));
  const release = gate.release(); await Promise.resolve(); advance(4000);
  await assert.rejects(release); assert.equal(timers.size, 0); assert.equal(gate.snapshot().released, 0); assert.equal(gate.snapshot().abandoned, 1); gate.close();
});

test("close cancels timers and records armed/captured abandonment before teardown", () => {
  for (const captured of [false, true]) {
    const { gate, timers } = setup(); gate.arm(id, 2); if (captured) gate.capture(request(), response(), async () => ({ kind: "fulfilled" }));
    gate.close(); assert.equal(timers.size, 0); assert.equal(gate.snapshot().armed, false); assert.equal(gate.snapshot().remaining, 0); assert.equal(gate.snapshot().abandoned, 1);
    assert.equal(notesCleanupConfirmed(gate.snapshot()), false); assert.throws(() => gate.arm(id, 2));
  }
});

test("cleanup predicates reject unfinished, excess or invented completion counts", () => {
  const value = { closed: true, failed: false, abandoned: 0, remaining: 0, armed: false, captured: 4, released: 4, fulfilled: 4, verified_canceled: 0 };
  assert.equal(notesCleanupConfirmed(value), true);
  for (const change of [{ closed: false }, { failed: true }, { abandoned: 1 }, { remaining: 1 }, { armed: true }, { captured: 5 }, { captured: true }, { released: 3 }]) assert.equal(notesCleanupConfirmed({ ...value, ...change }), false);
});

test("actual stats must be closed typed zero-execution observations, never default constants", () => {
  const value = { id: 1, kind: "notes_stats", state: "history_advanced", notes: 1, chats: 0, messages: 0, analysis: 0, engine_calls: 0, enqueue_calls: 0, provider_calls: 0, forbidden_requests: 0 };
  assert.equal(notesStats(value).notes, 1); assert.equal(Object.hasOwn(notesStats(value), "id"), false);
  for (const key of ["chats", "messages", "analysis", "engine_calls", "enqueue_calls", "provider_calls", "forbidden_requests"]) assert.throws(() => notesStats({ ...value, [key]: 1 }), /real_notes_execution_detected/);
  for (const change of [{ notes: true }, { notes: -1 }, { notes: 0.5 }, { state: "arbitrary" }, { extra: 1 }, { provider_calls: "0" }]) assert.throws(() => notesStats({ ...value, ...change }));
});

test("only a single explicit no-store header is private response evidence", () => {
  assert.equal(notesResponsePrivate({ headers: [["Cache-Control", "private, no-store"]] }), true);
  for (const headers of [[], [["Cache-Control", "private"]], [["Cache-Control", "no-store-ish"]], [["Cache-Control", "no-store"], ["cache-control", "no-store"]]]) assert.equal(notesResponsePrivate({ headers }), false);
});

test("physical key dispatch preserves native activation while invalid keys fail before sending", async () => {
  const calls = []; for (const key of ["Tab", "Enter", "Escape"]) await notesRealKey((method, args) => calls.push([method, args]), key);
  assert.equal(calls.length, 6); assert.equal(calls[0][1].text, undefined); assert.equal(calls[2][1].text, "\r"); assert.equal(calls[4][1].key, "Escape");
  await assert.rejects(notesRealKey(() => { throw Error("sent"); }, "F12"), /real_notes_key_invalid/);
});

test("the finite prospectively authored packet has exactly22 checks and preserves literal inert text", () => {
  assert.equal(REAL_NOTES_CASES.length, 22); assert.equal(new Set(REAL_NOTES_CASES).size, 22); assert.equal(Object.isFrozen(REAL_NOTES_CASES), true);
  assert.equal(REAL_NOTES_GOLD.body, "Fictional team note: review volume by month.\n\tLiteral <metric> text.");
  assert.equal(REAL_NOTES_GOLD.correctedBody, "User claim: Orchid volume means completed fictional items. Verify before use.");
});

test("invalid initial clocks and backwards movement between arms permanently fail the gate", async () => {
  for (const time of [NaN, Infinity, -1, "0"]) {
    const { gate, clockOnly } = setup(); clockOnly(time); assert.throws(() => gate.arm(id, 2), /real_notes_gate_clock_invalid/);
    clockOnly(0); assert.throws(() => gate.arm(id, 2), /real_notes_gate_clock_invalid/); gate.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), false);
  }
  const { gate, clockOnly } = setup(); clockOnly(10); gate.arm(id, 2); gate.capture(request(), response(), async () => ({ kind: "fulfilled" })); await gate.release();
  clockOnly(9); assert.throws(() => gate.arm(id, 2), /real_notes_gate_clock_invalid/); gate.close();
});

test("cleanup cannot invoke a caller accessor or accept an incomplete report", () => {
  let getters = 0; const value = Object.defineProperty({}, "closed", { get() { getters++; return true; } });
  assert.equal(notesCleanupConfirmed(value), false); assert.equal(getters, 0);
  for (const bad of [null, undefined, {}, { closed: true }]) assert.equal(notesCleanupConfirmed(bad), false);
});

const event = (fetchId = "interception-1", networkId = "123.4") => ({ requestId: fetchId, networkId, request: request() });
function canceledError() {
  return Object.assign(Error("fixed classified protocol rejection"), { canceled: true, protocolReason: "request_no_longer_exists",
    browserDiagnostic: { method: "Fetch.fulfillRequest", protocol_reason: "request_no_longer_exists" } });
}
test("only a same-request actual canceled event plus exact CDP rejection can settle an undelivered response", async () => {
  const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event());
  assert.equal(evidence.observe({ requestId: "123.4", canceled: true }), true);
  assert.deepEqual(await evidence.finish(token, async () => { throw canceledError(); }), { kind: "verified_browser_canceled" });
  assert.deepEqual(evidence.snapshot(), { registered: 1, fulfilled: 0, verified_canceled: 1, pending: 0, failed: false, closed: false });
  evidence.close(); assert.equal(notesCancellationCleanupConfirmed(evidence.snapshot()), true);
});

test("fulfillment is counted separately and neither raw payloads nor network identifiers enter snapshots", async () => {
  const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event());
  assert.deepEqual(await evidence.finish(token, async () => ({})), { kind: "fulfilled" });
  evidence.close(); assert.equal(notesCancellationCleanupConfirmed(evidence.snapshot()), true);
  assert.equal(evidence.snapshot().fulfilled, 1); assert.equal(evidence.snapshot().verified_canceled, 0);
  assert.ok(!JSON.stringify(evidence.snapshot()).includes("123.4")); assert.ok(!JSON.stringify(evidence.snapshot()).includes(REAL_NOTES_GOLD.body));
});

test("missing, false, other-request or wrongly typed events never convert an exception into cancellation success", async () => {
  for (const observed of [null, { requestId: "123.4", canceled: false }, { requestId: "999.9", canceled: true }, { requestId: "123.4" }]) {
    const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event()); if (observed) assert.equal(evidence.observe(observed), false);
    await assert.rejects(evidence.finish(token, async () => { throw canceledError(); }), /real_notes_fulfill_failed/);
    evidence.close(); assert.equal(notesCancellationCleanupConfirmed(evidence.snapshot()), false); assert.equal(evidence.snapshot().verified_canceled, 0);
  }
  for (const value of [1, "true", null]) {
    const evidence = new NotesCancellationEvidence(origin); evidence.bind(event()); assert.throws(() => evidence.observe({ requestId: "123.4", canceled: value }), /real_notes_cancellation_event_invalid/); evidence.close();
  }
});

test("cancellation identity/accessors cannot be coerced, replayed, rebound or inherited from another capture", async () => {
  const evidence = new NotesCancellationEvidence(origin), first = evidence.bind(event());
  assert.throws(() => evidence.bind(event()), /real_notes_cancellation_binding_invalid/);
  assert.throws(() => evidence.bind(event("interception-2", "123.4")), /real_notes_cancellation_binding_invalid/);
  const second = evidence.bind(event("interception-2", "123.5")); evidence.observe({ requestId: "123.4", canceled: true });
  await assert.rejects(evidence.finish(second, async () => { throw canceledError(); }), /real_notes_fulfill_failed/);
  await assert.rejects(evidence.finish(first, async () => ({}))); evidence.close();
  for (const key of ["requestId", "networkId", "request"]) {
    let reads = 0; const value = Object.defineProperty(event(), key, { get() { reads++; throw Error("getter"); } });
    assert.throws(() => new NotesCancellationEvidence(origin).bind(value), /real_notes_record_invalid/); assert.equal(reads, 0);
  }
  const fresh = new NotesCancellationEvidence(origin); fresh.bind(event()); let reads = 0;
  assert.throws(() => fresh.observe(Object.defineProperty({ requestId: "123.4" }, "canceled", { get() { reads++; return true; } })), /real_notes_record_invalid/); assert.equal(reads, 0); fresh.close();
});

test("unknown errors and navigation/shutdown flags cannot substitute for exact classified request cancellation", async () => {
  for (const change of [{ protocolReason: "target_no_longer_exists" }, { canceled: false }, { browserDiagnostic: { method: "Runtime.evaluate", protocol_reason: "request_no_longer_exists" } },
    { browserDiagnostic: { method: "Fetch.fulfillRequest", protocol_reason: "unknown" } }, { browserDiagnostic: null }]) {
    const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event()); evidence.observe({ requestId: "123.4", canceled: true });
    await assert.rejects(evidence.finish(token, async () => { throw Object.assign(canceledError(), change, { shutdownSessionMissing: true, navigating: true }); }), /real_notes_fulfill_failed/); evidence.close();
  }
  const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event());
  await assert.rejects(evidence.finish(token, async () => { throw Object.assign(canceledError(), { shutdownSessionMissing: true, navigating: true }); }), /real_notes_fulfill_failed/); evidence.close();
});

test("canceled finish classification still obeys the original gate lease and cannot be retried", async () => {
  const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event()), { gate, clockOnly } = setup();
  evidence.observe({ requestId: "123.4", canceled: true }); gate.arm(id, 2);
  gate.capture(request(), response(), () => evidence.finish(token, async () => { clockOnly(4000); throw canceledError(); }));
  await assert.rejects(gate.release()); assert.equal(gate.snapshot().verified_canceled, 0); assert.equal(gate.snapshot().released, 0);
  await assert.rejects(evidence.finish(token, async () => ({})), /real_notes_cancellation_finish_invalid/); gate.close(); evidence.close();
});

test("finish outcomes are closed and evidence queues remain bounded and unambiguous at cleanup", async () => {
  for (const outcome of [undefined, {}, { kind: "canceled" }, { kind: "fulfilled", extra: true }, Object.defineProperty({}, "kind", { get() { throw Error("must not invoke"); } })]) {
    const { gate } = setup(); gate.arm(id, 2); gate.capture(request(), response(), async () => outcome); await assert.rejects(gate.release()); gate.close();
  }
  const evidence = new NotesCancellationEvidence(origin);
  for (let i = 0; i < 4; i++) { const token = evidence.bind(event(`interception-${i}`, `123.${i}`)); await evidence.finish(token, async () => ({})); }
  assert.throws(() => evidence.bind(event("interception-5", "123.5")), /real_notes_cancellation_capacity/); evidence.close(); assert.equal(notesCancellationCleanupConfirmed(evidence.snapshot()), true);
  const abandoned = new NotesCancellationEvidence(origin); abandoned.bind(event()); abandoned.close(); assert.equal(notesCancellationCleanupConfirmed(abandoned.snapshot()), false);
});

test("network and Fetch identity values are exact bounded strings without coercion", () => {
  for (const invalid of [undefined, null, true, 1, ["123.4"], {}, "", "x".repeat(257), "123.4\n"]) {
    for (const key of ["requestId", "networkId"]) assert.throws(() => new NotesCancellationEvidence(origin).bind({ ...event(), [key]: invalid }));
    const evidence = new NotesCancellationEvidence(origin); evidence.bind(event()); assert.throws(() => evidence.observe({ requestId: invalid, canceled: true })); evidence.close();
  }
});

test("verified cancellation within the original lease has separate completed-undelivered accounting", async () => {
  const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event()), { gate, clockOnly } = setup();
  evidence.observe({ requestId: "123.4", canceled: true }); gate.arm(id, 2);
  gate.capture(request(), response(), () => evidence.finish(token, async () => { clockOnly(3999); throw canceledError(); }));
  assert.equal(await gate.release(), "verified_browser_canceled");
  assert.equal(gate.snapshot().fulfilled, 0); assert.equal(gate.snapshot().verified_canceled, 1); assert.equal(gate.snapshot().released, 1);
  gate.close(); evidence.close(); assert.equal(notesCleanupConfirmed(gate.snapshot()), true); assert.equal(notesCancellationCleanupConfirmed(evidence.snapshot()), true);
});

test("a bound cancellation callback cannot run concurrently twice or settle after close", async () => {
  const evidence = new NotesCancellationEvidence(origin), token = evidence.bind(event()); let complete;
  const work = evidence.finish(token, () => new Promise(resolve => { complete = resolve; }));
  await assert.rejects(evidence.finish(token, async () => ({})), /real_notes_cancellation_finish_invalid/);
  evidence.close(); complete(); await assert.rejects(work, /real_notes_fulfill_failed/);
  assert.equal(evidence.snapshot().fulfilled, 0); assert.equal(notesCancellationCleanupConfirmed(evidence.snapshot()), false);
});
