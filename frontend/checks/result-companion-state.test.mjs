import assert from "node:assert/strict";
import test from "node:test";
import { createResultCompanionController } from "../src/features/resultCompanion/state.js";
import { resultBinding, isSavedResultCandidate, sameResultBinding } from "../src/features/resultCompanion/binding.js";
import { resultFollowupFields } from "../src/features/resultCompanion/followup.js";
import { prepareGuidedQuestion } from "../src/services/guidedQuestion.js";
import { boundedCompanionQuestion } from "../src/services/companionClient.js";
import { canApplyResultDraft } from "../src/features/resultCompanion/apply.js";
import { resultFixture, IDS } from "./result-companion-fixture.mjs";

const pending = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
function controllerFixture() {
  const f = resultFixture(), calls = [], states = []; let valid = true, closed = 0, auth = 0;
  const controller = createResultCompanionController({ binding: f.binding, options: { ownerId: IDS.owner },
    api(...args) { const task = pending(); calls.push({ args, task }); return task.promise; }, onState: value => states.push(value),
    assertCurrent() { if (!valid) throw Error("binding replaced"); }, onInvalidated: () => closed++, onAuthFailure: () => auth++ });
  return { ...f, controller, calls, states, invalidate: () => { valid = false; }, counts: () => ({ closed, auth }) };
}

test("only complete durable authorized saved results are eligible; permissions and payload replacement invalidate selection", () => {
  const f = resultFixture(); assert.equal(isSavedResultCandidate(f.message), true);
  for (const patch of [{ historical: false }, { status: "pending" }, { resultUnavailable: true }, { requestId: "local-request" }, { response: { status: "error" } }]) assert.equal(isSavedResultCandidate({ ...f.message, ...patch }), false);
  assert.equal(resultBinding(f.chat, IDS.owner, IDS.message, false), null);
  assert.equal(resultBinding({ ...f.chat, durable: false }, IDS.owner, IDS.message, true), null);
  const old = f.binding; assert.equal(sameResultBinding(old, resultBinding(f.chat, IDS.owner, IDS.message, true)), true);
  f.message.response = { ...f.message.response }; assert.equal(sameResultBinding(old, resultBinding(f.chat, IDS.owner, IDS.message, true)), false);
  f.chat.active.analyses[IDS.request].state = "cancelled"; assert.equal(resultBinding(f.chat, IDS.owner, IDS.message, true), null);
});

test("reads are single flight, invalid columns do nothing, and changing column aborts/fences the prior reply", async () => {
  const f = controllerFixture(), first = f.controller.load(); await f.controller.load(); await f.controller.select(9);
  assert.equal(f.calls.length, 1);
  const next = f.controller.select(1); assert.equal(f.calls[0].args[2].signal.aborted, true); assert.equal(f.calls.length, 2);
  f.calls[0].task.resolve(f.reply); await first; assert.equal(f.controller.snapshot().reply, null);
  const second = { ...f.reply, brief: { ...f.reply.brief, field: { ...f.reply.brief.field, index: 1 } } };
  f.calls[1].task.resolve(second); await next; assert.equal(f.controller.snapshot().columnIndex, 1); assert.equal(f.controller.snapshot().reply, second);
});

test("close and request/history/owner invalidation clear data and discard late success", async () => {
  for (const invalidation of ["close", "binding"]) {
    const f = controllerFixture(), task = f.controller.load(), count = f.states.length;
    if (invalidation === "close") f.controller.close(); else f.invalidate();
    f.calls[0].task.resolve(f.reply); await task;
    assert.equal(f.controller.snapshot().phase, "closed"); assert.equal(f.controller.snapshot().reply, null); assert.equal(f.states.length, count);
    assert.equal(f.calls[0].args[2].signal.aborted, true);
  }
});

test("fixed errors clear facts and timeout remains manually recoverable without automatic retry", async () => {
  for (const [error, phase] of [[{ status: 404 }, "unavailable"], [{ status: 403 }, "denied"], [{ status: 409 }, "stale"], [{ status: 503 }, "error"], [new DOMException("PRIVATE", "AbortError"), "error"]]) {
    const f = controllerFixture(), task = f.controller.load(); f.calls[0].task.reject(error); await task;
    assert.equal(f.controller.snapshot().phase, phase); assert.equal(f.controller.snapshot().reply, null); assert.equal(f.calls.length, 1);
    assert.equal(JSON.stringify(f.controller.snapshot()).includes("PRIVATE"), false);
    const retry = f.controller.load(); f.calls[1].task.resolve(f.reply); await retry; assert.equal(f.controller.snapshot().phase, "ready");
  }
});

test("authentication loss closes and asks the normal auth layer to refresh", async () => {
  const f = controllerFixture(), task = f.controller.load(); f.calls[0].task.reject({ status: 401 }); await task;
  assert.equal(f.controller.snapshot().phase, "closed"); assert.deepEqual(f.counts(), { closed: 1, auth: 1 });
});

test("follow-up choices reuse the existing grammar with all unknown fields explicit and no invented scope", () => {
  for (const intent of ["verify_scope", "missing_values", "compare_field"]) {
    const fields = resultFollowupFields(intent, 'Returned "sample" value'), prepared = prepareGuidedQuestion(fields);
    assert.equal(fields.grouping, ""); assert.equal(fields.period, ""); assert.equal(fields.filters, "");
    assert.deepEqual(prepared.missing, ["grouping", "period", "filters"]);
    assert.match(prepared.question, /Grouping: Not specified\./); assert.match(prepared.question, /Do not invent omitted details/);
    assert.equal(boundedCompanionQuestion(prepared.question), prepared.question);
  }
  assert.equal(resultFollowupFields("execute", "value"), null);
  assert.equal(resultFollowupFields("compare_field", "x".repeat(401)).measure, "");
  for (const value of ["x".repeat(2001), "bad\u0000text", "\ud800", " "]) assert.throws(() => boundedCompanionQuestion(value));
});

test("apply requires the same owner, session, target and original composer draft plus current permission", () => {
  const { binding } = resultFixture(), scope = { ownerId: IDS.owner, csrfToken: "current-session", token: binding.token, draft: "Keep my original draft" };
  const input = { scope, binding, ownerId: IDS.owner, csrfToken: "current-session", canQuery: true, archived: false,
    draft: scope.draft, expected: { token: binding.token, draft: scope.draft }, value: "My explicitly reviewed follow-up" };
  assert.equal(canApplyResultDraft(input), true);
  for (const change of [{ scope: null }, { binding: null }, { expected: null }, { ownerId: IDS.chat }, { csrfToken: "replacement-session" },
    { canQuery: false }, { archived: true }, { draft: "A newer composer edit" }, { binding: { ...binding, token: "new-result" } },
    { expected: { token: binding.token, draft: "new-draft" } }, { value: "" }, { value: "x".repeat(2001) }, { value: "bad\u0000text" }])
    assert.equal(canApplyResultDraft({ ...input, ...change }), false);
  assert.equal(input.draft, "Keep my original draft"); // A guard cannot mutate or submit it.
});

test("local questions and server text honor code-point bounds and reject malformed Unicode", async () => {
  const f = resultFixture(), original = f.chat.messages[0];
  original.content = "\u{1f30a}".repeat(2000);
  assert.equal(resultBinding(f.chat, IDS.owner, IDS.message, true).question, original.content);
  const { decodeResultBrief } = await import("../src/features/resultCompanion/contract.js");
  const binding = resultBinding(f.chat, IDS.owner, IDS.message, true); f.reply.brief.question = original.content;
  assert.equal(decodeResultBrief(f.reply, binding, 0).brief.question, original.content);
  for (const value of ["x".repeat(2001), "\ud800", "bad\u0000text"]) {
    original.content = value; assert.equal(resultBinding(f.chat, IDS.owner, IDS.message, true).question, null);
    f.reply.brief.question = value; assert.throws(() => decodeResultBrief(f.reply, { ...binding, question: null }, 0));
  }
});
