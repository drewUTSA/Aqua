import assert from "node:assert/strict";
import test from "node:test";
import { readResultBrief } from "../src/features/resultCompanion/api.js";
import { decodeResultBrief } from "../src/features/resultCompanion/contract.js";
import { activateSession, captureHistory, clearHistory } from "../src/services/historyAuthority.js";
import { resultFixture, IDS } from "./result-companion-fixture.mjs";

test("exact sidecar extrema retain sub-cent and unsafe integer precision and cite original rows", () => {
  const f = resultFixture(), value = decodeResultBrief(f.reply, f.binding, 0);
  assert.equal(value.brief.numeric.maximum.value, "9007199254740993.01");
  assert.equal(value.brief.numeric.minimum.value, "-0.0000000001");
  assert.deepEqual(value.brief.numeric.minimum.witness_rows, [1, 3]);
  assert.equal(value.brief.field.unit, null);
  f.reply.brief.numeric.minimum.value = "100";
  assert.equal(value.brief.numeric.minimum.value, "-0.0000000001");
});

test("legacy and empty saved results keep honest limitations without numerical comparisons", () => {
  for (const options of [{ legacy: true }, { empty: true }]) {
    const f = resultFixture(options), value = decodeResultBrief(f.reply, f.binding, 0);
    assert.equal(value.brief.numeric, null);
    assert.equal(value.brief.source.freshness_at, null);
    assert.equal(value.brief.scope.filters, "unknown");
    if (options.legacy) { assert.equal(value.brief.scope.truncated, null); assert.equal(value.brief.source.id, null); }
    else assert.equal(value.brief.counts.returned_rows, 0);
  }
});

test("owner, chat, request, assistant, job and selected-field bindings reject substitution", () => {
  const f = resultFixture();
  for (const change of [v => { v.owner_id = IDS.input; }, v => { v.chat_id = IDS.input; }, v => { v.request_id = IDS.input; },
    v => { v.assistant_message_id = IDS.input; }, v => { v.job_version++; }, v => { v.job_version = true; },
    v => { v.brief.field.index = 1; }, v => { v.brief.field.key = "tag"; }, v => { v.brief.field.label = "Different meaning"; },
    v => { v.brief.question = "Another question"; }]) {
    const value = structuredClone(f.reply); change(value); assert.throws(() => decodeResultBrief(value, f.binding, 0), { code: "invalid_response" });
  }
});

test("witnesses require real saved numeric cells and reject rounding, bad ties and missing coordinates", () => {
  const f = resultFixture();
  for (const change of [v => { v.brief.numeric.maximum.value = "9007199254740993.00"; }, v => { v.brief.numeric.minimum.value = "-1e-10"; },
    v => { v.brief.numeric.minimum.witness_rows = [1, 1]; }, v => { v.brief.numeric.minimum.witness_rows = [3, 1]; },
    v => { v.brief.numeric.minimum.witness_rows = [2]; }, v => { v.brief.numeric.minimum.witness_rows = [4]; },
    v => { v.brief.numeric.minimum.ties = 0; }, v => { v.brief.numeric.minimum.ties = 4; }, v => { v.brief.numeric.maximum.value = true; }]) {
    const value = structuredClone(f.reply); change(value); assert.throws(() => decodeResultBrief(value, f.binding, 0), { code: "invalid_response" });
  }
  const detached = { ...f.binding, table: structuredClone(f.binding.table) };
  assert.throws(() => decodeResultBrief(f.reply, detached, 0), { code: "invalid_response" });
  const unproven = { ...f.binding, table: structuredClone(f.binding.table) };
  unproven.table.rows[0].value = Number("9007199254740993.01");
  unproven.table.rows[1].value = -1e-10; unproven.table.rows[3].value = -1e-10;
  const rounded = structuredClone(f.reply); rounded.brief.numeric.maximum.value = String(unproven.table.rows[0].value);
  assert.throws(() => decodeResultBrief(rounded, unproven, 0), { code: "invalid_response" });
});

test("invented units, freshness, scope, malformed checks and unsafe fields fail closed", () => {
  const f = resultFixture();
  for (const change of [v => { v.brief.field.unit = "USD"; }, v => { v.brief.source.freshness_at = v.brief.source.generated_at; },
    v => { v.brief.source.id = "b".repeat(64); }, v => { v.brief.source.generated_at = "2026-11-17T18:00:00"; },
    v => { v.brief.scope.filters = "same as before"; }, v => { v.brief.scope.truncated = false; }, v => { v.brief.execution_enabled = true; },
    v => { v.brief.counts.missing_values = 2; }, v => { v.brief.checks.reverse(); }, v => { v.brief.checks[0].text = "Cause is fraud"; },
    v => { v.brief.followup_intents.push("send_payment"); }, v => { v.brief.sql = "PRIVATE_SENTINEL"; }]) {
    const value = structuredClone(f.reply); change(value); assert.throws(() => decodeResultBrief(value, f.binding, 0), { code: "invalid_response" });
  }
  let read = false; const value = structuredClone(f.reply);
  Object.defineProperty(value.brief, "question", { get() { read = true; return "private"; } });
  assert.throws(() => decodeResultBrief(value, f.binding, 0)); assert.equal(read, false);
});

test("client sends only the fixed result identity and selected index, with private bounded transport", async t => {
  clearHistory(); const f = resultFixture(), calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return new Response(JSON.stringify(f.reply), { headers: { "Content-Type": "application/json" } }); });
  await readResultBrief(f.binding, 0, { ownerId: IDS.owner, csrfToken: "fixture-csrf", persona: "manager", rows: ["PRIVATE"] });
  assert.equal(calls.length, 1); assert.equal(calls[0].url, "/api/v1/companion/result-brief");
  assert.deepEqual(JSON.parse(calls[0].init.body), { schemaVersion: 1, request_id: IDS.request, column_index: 0 });
  assert.equal(calls[0].init.cache, "no-store"); assert.equal(calls[0].init.credentials, "same-origin"); assert.equal(calls[0].init.redirect, "error");
  for (const index of [true, 0.5, -1, 2]) await assert.rejects(readResultBrief(f.binding, index, { ownerId: IDS.owner, csrfToken: "fixture-csrf" }), { code: "invalid_input" });
  await assert.rejects(readResultBrief(f.binding, 0, { ownerId: IDS.input }), { code: "invalid_input" }); assert.equal(calls.length, 1);
});

test("32KiB response cap cancels oversized bodies before retaining result data", async t => {
  clearHistory(); const f = resultFixture(); let cancelled = false, pulls = 0;
  const body = new ReadableStream({ pull() { pulls++; }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  t.mock.method(globalThis, "fetch", async () => new Response(body, { headers: { "Content-Type": "application/json", "Content-Length": "32769" } }));
  await assert.rejects(readResultBrief(f.binding, 0, { ownerId: IDS.owner, csrfToken: "fixture-csrf" }), { code: "invalid_response" });
  assert.equal(cancelled, true); assert.equal(pulls, 0);
});

test("a real held transport reply cannot cross account and session replacement", async t => {
  clearHistory(); const f = resultFixture(); let finish;
  activateSession({ user: { id: IDS.owner }, csrf_token: "csrf-one" });
  t.mock.method(globalThis, "fetch", () => new Promise(resolve => { finish = resolve; }));
  const task = readResultBrief(f.binding, 0, { ownerId: IDS.owner, csrfToken: "csrf-one" });
  activateSession({ user: { id: IDS.input }, csrf_token: "csrf-two" }); finish(new Response(JSON.stringify(f.reply), { headers: { "Content-Type": "application/json" } }));
  await assert.rejects(task, { name: "AbortError" }); clearHistory();
});

test("a target opened before a lazy import cannot adopt a replacement history to start its read", async t => {
  clearHistory(); const f = resultFixture(); let calls = 0;
  activateSession({ user: { id: IDS.owner }, csrf_token: "csrf-one" }); const historyContext = captureHistory("csrf-one");
  activateSession({ user: { id: IDS.owner }, csrf_token: "csrf-two" });
  t.mock.method(globalThis, "fetch", async () => { calls++; return new Response(JSON.stringify(f.reply)); });
  await assert.rejects(readResultBrief(f.binding, 0, { ownerId: IDS.owner, csrfToken: "csrf-two", historyContext }), { name: "AbortError" });
  assert.equal(calls, 0); clearHistory();
});
