import assert from "node:assert/strict";
import test from "node:test";
import { createBankDemoController } from "../src/features/bankDemo/state.js";

const context = { sourceRevision: "a".repeat(64), reports: [{ id: "vendor_review_summary" }, { id: "audit_issue_summary" }] };
const pending = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function fixture() {
  const calls = [], states = []; let valid = true, invalidated = 0, auth = 0;
  const api = Object.fromEntries(["context", "report"].map(kind => [kind, (...args) => { const task = pending(); calls.push({ kind, args, task }); return task.promise; }]));
  const controller = createBankDemoController({ api, options: { ownerId: "owner-one" }, assertCurrent() { if (!valid) throw Error("scope changed"); },
    onState: value => states.push(value), onInvalidated: () => invalidated++, onAuthFailure: () => auth++ });
  return { controller, calls, states, invalidate: () => { valid = false; }, counts: () => ({ invalidated, auth }) };
}
async function ready(f) { const job = f.controller.load(); f.calls.at(-1).task.resolve(context); await job; }

test("unavailable evidence clears old figures and a changed request invalidates late reads", async () => {
  const f = fixture(); await ready(f);
  const id = context.reports[0].id;
  f.controller.select(id);
  const first = f.controller.read(); f.calls.at(-1).task.resolve({ reportId: id }); await first;
  const requirements = { source: "institution_record", period_start: null, period_end: null };
  const limited = f.controller.read(requirements), call = f.calls.at(-1);
  assert.equal(f.controller.snapshot().result, null); assert.deepEqual(call.args.at(-1).requirements, requirements);
  const unavailable = { reason: "institution_source_unavailable" }; call.task.resolve({ unavailable }); await limited;
  assert.deepEqual(f.controller.snapshot().limitation, unavailable); assert.equal(f.controller.snapshot().result, null);
  f.controller.select(id); assert.equal(f.controller.snapshot().limitation, null);
  const late = f.controller.read(); f.controller.select(""); f.calls.at(-1).task.resolve({ reportId: id }); await late;
  assert.equal(f.controller.snapshot().selected, ""); assert.equal(f.controller.snapshot().result, null);
});

test("report reading is explicit, authorized by current menu, single-flight and never submits or persists", async () => {
  const f = fixture(); await ready(f);
  await f.controller.read(); assert.equal(f.calls.length, 1);
  f.controller.select("foreign_report"); assert.equal(f.controller.snapshot().selected, "");
  f.controller.select(context.reports[0].id);
  const read = f.controller.read(); await f.controller.read();
  assert.equal(f.calls.length, 2); assert.equal(f.calls[1].kind, "report");
  assert.equal(f.calls[1].args[0], context.reports[0].id); assert.equal(f.calls[1].args[1], context);
  const result = { reportId: context.reports[0].id };
  f.calls[1].task.resolve(result); await read;
  assert.equal(f.controller.snapshot().result, result);
  assert.deepEqual(Object.keys(f.controller).sort(), ["close", "current", "load", "read", "select", "snapshot"]);
});

test("close aborts and discards late context or report replies even if transport ignores abort", async () => {
  for (const stage of ["context", "report"]) {
    const f = fixture(); if (stage === "report") { await ready(f); f.controller.select(context.reports[0].id); }
    const job = stage === "context" ? f.controller.load() : f.controller.read();
    const call = f.calls.at(-1), options = call.args.at(-1); f.controller.close();
    assert.equal(options.signal.aborted, true); call.task.resolve(context); await job;
    assert.equal(f.controller.snapshot().phase, "closed"); assert.equal(f.controller.snapshot().result, null);
  }
});

test("changing report discards old figures and fences a late prior report", async () => {
  const f = fixture(); await ready(f); f.controller.select(context.reports[0].id);
  const first = f.controller.read(); f.controller.select(context.reports[1].id);
  f.calls[1].task.resolve({ reportId: context.reports[0].id }); await first;
  assert.equal(f.controller.snapshot().selected, context.reports[1].id); assert.equal(f.controller.snapshot().result, null);
});

test("owner/session/history invalidation closes before a late response can publish", async () => {
  const f = fixture(), job = f.controller.load(), before = f.states.length;
  f.invalidate(); f.calls[0].task.resolve(context); await job;
  assert.equal(f.states.length, before); assert.equal(f.controller.snapshot().phase, "closed"); assert.equal(f.counts().invalidated, 1);
});

test("disabled, denied, stale-source and unavailable responses have separate repair states with no retained facts", async () => {
  for (const [status, phase] of [[404, "unavailable"], [403, "denied"], [409, "stale"], [503, "error"]]) {
    const f = fixture(); await ready(f); f.controller.select(context.reports[0].id);
    const job = f.controller.read(); f.calls[1].task.reject({ status, message: "PRIVATE_SENTINEL" }); await job;
    const state = f.controller.snapshot(); assert.equal(state.phase, phase); assert.equal(state.result, null); assert.equal(state.context, null);
    assert.equal(JSON.stringify(state).includes("PRIVATE_SENTINEL"), false);
  }
});

test("authentication loss closes the demo and requests normal session refresh", async () => {
  const f = fixture(), job = f.controller.load(); f.calls[0].task.reject({ status: 401 }); await job;
  assert.equal(f.controller.snapshot().phase, "closed"); assert.deepEqual(f.counts(), { invalidated: 1, auth: 1 });
});
