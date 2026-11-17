import assert from "node:assert/strict";
import test from "node:test";
import { bankDemoContext, bankDemoReport } from "../src/features/bankDemo/api.js";
import { decodeBankContext, decodeBankReport } from "../src/features/bankDemo/contract.js";
import { activateSession, clearHistory } from "../src/services/historyAuthority.js";
import { contextEnvelope, reportEnvelope, ownerId, option } from "./bank-demo-fixture.mjs";

const context = () => decodeBankContext(contextEnvelope(), ownerId);
const decode = value => decodeBankReport(value, ownerId, option.id, context());
const json = value => new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } });

test("fixed private routes send only report ID and revision, never roles, composer text or authority", async t => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json(init.method === "GET" ? contextEnvelope() : reportEnvelope()); });
  const menu = await bankDemoContext({ ownerId });
  const report = await bankDemoReport(option.id, menu, { ownerId, csrfToken: "csrf", persona: "manager", question: "PRIVATE_DRAFT" });
  assert.equal(report.rows[0][2], "1461250.00");
  assert.deepEqual(calls.map(call => call.url), ["/api/v1/bank-demo/context", "/api/v1/bank-demo/reports"]);
  assert.deepEqual(JSON.parse(calls[1].init.body), { schemaVersion: 1, report_id: option.id, expected_source_revision: "a".repeat(64) });
  for (const { init } of calls) { assert.equal(init.cache, "no-store"); assert.equal(init.credentials, "same-origin"); assert.equal(init.redirect, "error"); }
  assert.equal(calls[1].init.headers["X-CSRF-Token"], "csrf");
});

test("context rejects cross-owner, client role claims, extra fields and unknown report/department bindings", () => {
  const other = "20000000-0000-4000-8000-000000000002";
  for (const change of [value => { value.owner_id = other; }, value => { value.role = "manager"; }, value => { value.context.persona = "admin"; },
    value => { value.context.persona = "none"; }, value => { value.reports[0].id = "send_payment"; }, value => { value.reports[0].department = "internal_audit"; },
    value => { value.context.executionEnabled = true; }, value => { value.context.citationUrl = "javascript:bad()"; }]) {
    const value = contextEnvelope(); change(value); assert.throws(() => decodeBankContext(value, ownerId), { code: "invalid_response" });
  }
  const none = contextEnvelope(); none.context.persona = "none"; none.reports = []; assert.equal(decodeBankContext(none, ownerId).reports.length, 0);
});

test("reports reject unknown fields, mismatched report/scope/source and authority claims before rendering", () => {
  for (const change of [value => { value.owner_id = "20000000-0000-4000-8000-000000000002"; }, value => { value.result.reportId = "audit_issue_summary"; },
    value => { value.result.department = "internal_audit"; }, value => { value.result.procedure.fictional = false; }, value => { value.result.approvalRecorded = true; },
    value => { value.result.rows[0].push("unexpected"); }, value => { value.result.monthly_series = {}; }, value => { value.result.procedure.citationUrl = "javascript:bad()"; }]) {
    const value = reportEnvelope(); change(value); assert.throws(() => decode(value), { code: "invalid_response" });
  }
  for (const field of ["sourceRevision", "guidanceRevision"]) { const value = reportEnvelope(); value.result[field] = "d".repeat(64); assert.throws(() => decode(value), { status: 409 }); }
});

test("exact numeric cells are never coerced, rounded or accepted as exponent/float/unsafe fields", () => {
  const value = reportEnvelope(); value.result.rows[0][2] = "9007199254740993.01";
  assert.equal(decode(value).rows[0][2], "9007199254740993.01");
  for (const invalid of [1461250, "1e9", "NaN", "1,200.00", "1.0", true, null]) {
    const changed = reportEnvelope(); changed.result.rows[0][2] = invalid; assert.throws(() => decode(changed), { code: "invalid_response" });
  }
  const shared = reportEnvelope(), result = decode(shared); shared.result.rows[0][2] = "0.00"; assert.equal(result.rows[0][2], "1461250.00");
});

test("getters, unpaired Unicode, overlong text and oversized DTOs fail closed", () => {
  const value = contextEnvelope(); let read = false;
  Object.defineProperty(value.context, "notice", { get() { read = true; return "PRIVATE"; } });
  assert.throws(() => decodeBankContext(value, ownerId), { code: "invalid_response" }); assert.equal(read, false);
  for (const text of ["bad\u0000text", "bad\u202etext", "\ud800", "x".repeat(4097)]) { const changed = reportEnvelope(); changed.result.procedure.text = text; assert.throws(() => decode(changed), { code: "invalid_response" }); }
  const huge = reportEnvelope(); huge.result.rows = Array.from({ length: 13 }, () => [...huge.result.rows[0]]); huge.result.rowCount = 13; assert.throws(() => decode(huge), { code: "invalid_response" });
});

test("32KiB transport cap cancels oversized streams before retaining them", async t => {
  let cancelled = false, pulls = 0;
  const body = new ReadableStream({ pull() { pulls++; }, cancel() { cancelled = true; } }, { highWaterMark: 0 });
  t.mock.method(globalThis, "fetch", async () => new Response(body, { headers: { "Content-Type": "application/json", "Content-Length": "32769" } }));
  await assert.rejects(bankDemoContext({ ownerId }), { code: "invalid_response" }); assert.equal(pulls, 0); assert.equal(cancelled, true);
});

test("a context borrowed from another owner cannot start a report read", async t => {
  const calls = t.mock.method(globalThis, "fetch", async () => json(reportEnvelope()));
  await assert.rejects(bankDemoReport(option.id, context(), { ownerId: "20000000-0000-4000-8000-000000000002", csrfToken: "csrf" }), { code: "invalid_input" });
  assert.equal(calls.mock.callCount(), 0);
});

test("a real late transport reply cannot cross account/session replacement", async t => {
  clearHistory(); activateSession({ user: { id: ownerId }, csrf_token: "csrf-a" }); let release;
  t.mock.method(globalThis, "fetch", () => new Promise(resolve => { release = resolve; }));
  const job = bankDemoContext({ ownerId, csrfToken: "csrf-a" });
  activateSession({ user: { id: "20000000-0000-4000-8000-000000000002" }, csrf_token: "csrf-b" }); release(json(contextEnvelope()));
  await assert.rejects(job, { name: "AbortError" }); clearHistory();
});
