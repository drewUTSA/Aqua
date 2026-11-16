import assert from "node:assert/strict";
import test from "node:test";
import { createCompanionToolsController } from "../src/hooks/companionToolsState.js";

const menu = { capabilities: [{ id: "app_help", behavior: "reviewed_lookup" }] };
const answer = { status: "answered", message: "Reviewed help", citations: [] };
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function setup(api = {}) {
  const updates = [], calls = [], options = { historyContext: {}, csrfToken: "fixture-csrf" };
  let valid = true, invalidations = 0, authFailures = 0;
  const wrap = (kind, fallback) => (...args) => { calls.push({ kind, args }); return (api[kind] || fallback)(...args); };
  const controller = createCompanionToolsController({ api: { menu: wrap("menu", async () => menu), help: wrap("help", async () => answer) },
    options, assertCurrent: () => { if (!valid) throw new Error("old owner or history"); },
    onState: (value) => updates.push(value), onInvalidated: () => { invalidations++; }, onAuthFailure: () => { authFailures++; } });
  return { controller, updates, calls, invalidateAuthority: () => { valid = false; }, counts: () => ({ invalidations, authFailures }) };
}

test("menu reads and explicit help actions are separate with no implicit submissions", async () => {
  const value = setup(); await value.controller.load();
  assert.equal(value.controller.snapshot().phase, "ready"); assert.deepEqual(value.calls.map((call) => call.kind), ["menu"]);
  await value.controller.ask("reset password");
  assert.equal(value.controller.snapshot().phase, "answered"); assert.equal(value.calls.length, 2);
  assert.equal(value.calls[1].args[0], "reset password"); assert.ok(value.calls[1].args[1].signal instanceof AbortSignal);
});

test("close aborts and clears state, and a late success cannot publish", async () => {
  const held = deferred(), value = setup({ help: () => held.promise }); await value.controller.load();
  const pending = value.controller.ask("PRIVATE-QUESTION"); value.controller.close();
  assert.equal(value.calls.at(-1).args[1].signal.aborted, true);
  const count = value.updates.length; held.resolve({ ...answer, message: "PRIVATE-LATE-ANSWER" }); await pending;
  assert.equal(value.updates.length, count); assert.deepEqual(value.controller.snapshot(), { phase: "closed", menu: null, answer: null, error: "" });
});

test("a newer request supersedes both late success and late failure", async () => {
  const first = deferred(), second = deferred(); let n = 0;
  const value = setup({ help: () => ++n === 1 ? first.promise : second.promise }); await value.controller.load();
  const a = value.controller.ask("first"), b = value.controller.ask("second");
  assert.equal(value.calls[1].args[1].signal.aborted, true);
  second.resolve({ ...answer, message: "new answer" }); await b;
  first.reject(new Error("old-private-error")); await a;
  assert.equal(value.controller.snapshot().answer.message, "new answer");
});

test("editing and changing tools abort old reads and remove their answer", async () => {
  const held = deferred(), value = setup({ help: () => held.promise }); await value.controller.load();
  const pending = value.controller.ask("first"); value.controller.edit(); held.resolve(answer); await pending;
  assert.equal(value.controller.snapshot().phase, "ready"); assert.equal(value.controller.snapshot().answer, null);
});

test("owner or history invalidation prevents an old response and clears the controller", async () => {
  const held = deferred(), value = setup({ help: () => held.promise }); await value.controller.load();
  const pending = value.controller.ask("PRIVATE-QUESTION"); value.invalidateAuthority(); held.resolve(answer); await pending;
  assert.equal(value.counts().invalidations, 1); assert.equal(value.controller.snapshot().phase, "closed");
  assert.equal(value.controller.snapshot().answer, null); assert.equal(value.calls.at(-1).args[1].signal.aborted, true);
});

test("disabled feature is honest unavailable state, retried only by an explicit read", async () => {
  const value = setup({ menu: async () => { throw { status: 404, message: "PRIVATE-SERVER" }; } });
  await value.controller.load(); assert.equal(value.controller.snapshot().phase, "unavailable");
  assert.match(value.controller.snapshot().error, /not available on this server/); assert.doesNotMatch(value.controller.snapshot().error, /PRIVATE/);
  assert.equal(value.calls.length, 1); await Promise.resolve(); assert.equal(value.calls.length, 1);
  await value.controller.load(); assert.equal(value.calls.length, 2);
});

test("auth revocation closes rather than retaining private help state", async () => {
  const value = setup({ help: async () => { throw { status: 401 }; } }); await value.controller.load(); await value.controller.ask("charts");
  assert.equal(value.controller.snapshot().phase, "closed"); assert.deepEqual(value.counts(), { invalidations: 1, authFailures: 1 });
});

test("abstention and failed read have distinct results and never echo raw errors", async () => {
  const value = setup({ help: async () => ({ ...answer, status: "abstained" }) }); await value.controller.load(); await value.controller.ask("unknown");
  assert.equal(value.controller.snapshot().phase, "abstained");
  const failed = setup({ help: async () => { throw new Error("PRIVATE-BODY"); } }); await failed.controller.load(); await failed.controller.ask("charts");
  assert.equal(failed.controller.snapshot().phase, "error"); assert.doesNotMatch(failed.controller.snapshot().error, /PRIVATE/);
  assert.equal(failed.calls.length, 2);
});

test("draft conflict is explicit and controller has no analysis or write operation", async () => {
  const value = setup(); await value.controller.load(); value.controller.conflict();
  assert.match(value.controller.snapshot().error, /composer draft changed/);
  assert.equal("submit" in value.controller, false); assert.equal(value.calls.length, 1);
});
