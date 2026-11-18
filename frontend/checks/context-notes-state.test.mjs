import assert from "node:assert/strict";
import test from "node:test";
import { createContextNotesController } from "../src/features/contextNotes/state.js";
import { library, readReply, prepared, noteId, otherId, requestId, fields, envelope } from "./context-notes-fixture.mjs";

const pending = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
function fixture() {
  let valid = true, invalidated = 0, auth = 0, ids = 0; const calls = [], states = [];
  const api = Object.fromEntries(["list", "read", "create", "save", "forget", "prepare"].map(kind => [kind, (...args) => {
    const task = pending(); calls.push({ kind, args, task }); return task.promise;
  }]));
  const controller = createContextNotesController({ api, options: { ownerId: "owner", csrfToken: "csrf", historyContext: "captured" },
    createId: () => { ids++; return requestId; }, assertCurrent() { if (!valid) throw Error("owner/history/target changed"); },
    onState: value => states.push(value), onInvalidated: () => invalidated++, onAuthFailure: () => auth++ });
  return { controller, calls, states, invalidate: () => { valid = false; }, counts: () => ({ invalidated, auth, ids }) };
}
async function settle(f, job, value) { f.calls.at(-1).task.resolve(value); await job; }
async function ready(f) { await settle(f, f.controller.load(), library()); }
async function selected(f) { await ready(f); await settle(f, f.controller.select(noteId), readReply()); }

test("library is metadata-only; reading is explicit and unavailable entries never request a body", async () => {
  const f = fixture(); await ready(f); assert.deepEqual(f.calls.map(call => call.kind), ["list"]);
  f.controller.select(otherId); assert.equal(f.calls.length, 1); assert.equal(f.controller.snapshot().note, null);
  await settle(f, f.controller.select(noteId), readReply()); assert.deepEqual(f.calls.map(call => call.kind), ["list", "read"]);
  assert.equal(f.controller.snapshot().editor.body, fields().body);
});

test("create is explicit, single-flight and uses one idempotency ID with the exact snapshot", async () => {
  const f = fixture(); await ready(f); f.controller.newNote(); await f.controller.save(); assert.equal(f.calls.length, 1);
  for (const [key, value] of Object.entries(fields())) f.controller.edit(key, value);
  const job = f.controller.save(); await f.controller.save(); f.controller.newNote(); await f.controller.load();
  assert.equal(f.counts().ids, 1); assert.equal(f.calls.length, 2); assert.equal(f.calls[1].kind, "create");
  assert.deepEqual(f.calls[1].args.slice(0, 3), [fields(), library().scope, requestId]);
  await settle(f, job, readReply()); assert.equal(f.controller.snapshot().note.id, noteId);
});

test("corrections require full save before fresh prepare; prepare and apply never call an analysis endpoint", async () => {
  const f = fixture(); await selected(f);
  f.controller.edit("body", "Corrected definition."); await f.controller.prepare(); assert.equal(f.calls.length, 2);
  const saved = readReply(); saved.note.revision = 3; saved.note.body = "Corrected definition.";
  await settle(f, f.controller.save(), saved); assert.equal(f.calls[2].kind, "save");
  const preparation = prepared(); preparation.source.revision = 3; preparation.draft = saved.note.body;
  await settle(f, f.controller.prepare(), preparation); assert.equal(f.calls[3].kind, "prepare");
  const applied = []; assert.equal(applied.length, 0); f.controller.editDraft("My reviewed question.");
  assert.equal(f.controller.apply(value => { applied.push(value); return true; }), true);
  assert.deepEqual(applied, ["My reviewed question."]); assert.deepEqual(f.calls.map(call => call.kind), ["list", "read", "save", "prepare"]);
});

test("editing, changing selection or composer conflict discards prepared application without overwriting composer", async () => {
  const f = fixture(); await selected(f); await settle(f, f.controller.prepare(), prepared());
  assert.equal(f.controller.apply(() => false), false); assert.equal(f.controller.snapshot().prepared, null);
  assert.match(f.controller.snapshot().error, /composer changed/);
  await settle(f, f.controller.prepare(), prepared()); f.controller.edit("label", "Correction"); assert.equal(f.controller.snapshot().prepared, null);
  f.controller.select(otherId); assert.equal(f.controller.snapshot().note, null); assert.equal(f.controller.snapshot().editor, null); assert.equal(f.controller.snapshot().draft, "");
});

test("every conflict or uncertain mutation clears held text and blocks retry until explicit reload", async () => {
  for (const status of [409, 0, 503, 422, 403]) {
    const f = fixture(); await selected(f); f.controller.edit("body", "Corrected private note");
    const job = f.controller.save(); f.calls.at(-1).task.reject({ status, message: "PRIVATE_ERROR_CANARY" }); await job;
    const state = f.controller.snapshot(); assert.equal(state.phase, "blocked"); assert.equal(state.library, null); assert.equal(state.editor, null);
    assert.equal(state.note, null); assert.equal(state.prepared, null); assert.equal(JSON.stringify(state).includes("PRIVATE_ERROR_CANARY"), false);
    const count = f.calls.length; await f.controller.save(); f.controller.newNote(); await f.controller.prepare(); assert.equal(f.calls.length, count);
    await settle(f, f.controller.load(), library()); assert.equal(f.controller.snapshot().phase, "ready");
  }
});

test("forget is separately confirmed, works on generic unavailable entries without grant, and drops held body before request", async () => {
  const f = fixture(), noGrant = library(); noGrant.scope.can_use = false; noGrant.items = [noGrant.items[1]];
  await settle(f, f.controller.load(), noGrant); f.controller.select(otherId); await f.controller.forget(); assert.equal(f.calls.length, 1);
  f.controller.confirmForget(true); const job = f.controller.forget(); assert.equal(f.calls[1].kind, "forget");
  await settle(f, job, envelope({ deleted: { id: otherId, revision: 5 } })); assert.equal(f.controller.snapshot().library.items.length, 0);
  assert.match(f.controller.snapshot().notice, /chat history are unchanged/);
  const g = fixture(); await selected(g); g.controller.confirmForget(true); const forgetting = g.controller.forget();
  assert.equal(g.controller.snapshot().note, null); assert.equal(g.controller.snapshot().editor, null); g.controller.close(); await settle(g, forgetting, {});
});

test("close and owner/history/target invalidation abort and discard every late operation", async () => {
  for (const action of ["list", "read", "save", "prepare", "forget"]) {
    const f = fixture(); let job;
    if (action !== "list") await selected(f);
    if (action === "list") job = f.controller.load();
    if (action === "read") { f.controller.select(otherId); job = f.controller.select(noteId); }
    if (action === "save") { f.controller.edit("body", "Changed."); job = f.controller.save(); }
    if (action === "prepare") job = f.controller.prepare();
    if (action === "forget") { f.controller.confirmForget(true); job = f.controller.forget(); }
    const call = f.calls.at(-1); f.controller.close(); assert.equal(call.args.at(-1).signal.aborted, true); call.task.resolve(readReply()); await job;
    assert.equal(f.controller.snapshot().phase, "closed"); assert.equal(f.controller.snapshot().note, null);
  }
  const f = fixture(), job = f.controller.load(), before = f.states.length; f.invalidate(); f.calls[0].task.resolve(library()); await job;
  assert.equal(f.states.length, before); assert.equal(f.counts().invalidated, 1);
});

test("authentication loss closes the library; disabled feature remains a recoverable availability state", async () => {
  for (const status of [401, 404]) {
    const f = fixture(), job = f.controller.load(); f.calls[0].task.reject({ status }); await job;
    assert.equal(f.controller.snapshot().phase, status === 401 ? "closed" : "unavailable");
    if (status === 401) assert.deepEqual(f.counts(), { invalidated: 1, auth: 1, ids: 0 });
  }
});
