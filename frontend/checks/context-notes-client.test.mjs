import assert from "node:assert/strict";
import test from "node:test";
import { listContextNotes, readContextNote, createContextNote, saveContextNote, forgetContextNote, prepareContextNote } from "../src/features/contextNotes/api.js";
import { activateSession, captureHistory, clearHistory, stampSession } from "../src/services/historyAuthority.js";
import { ownerId, otherId, scope, library, readReply, prepared, item, note, requestId, fields, envelope } from "./context-notes-fixture.mjs";

const json = (value, status = 200, headers = {}) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json", ...headers } });
test("six exact private routes carry captured history, CSRF and only closed note inputs", async t => {
  clearHistory(); const revision = "b".repeat(64), session = { user: { id: ownerId }, csrf_token: "csrf" };
  stampSession(session, json({}, 200, { "X-Aqua-History-Revision": revision }), captureHistory()); activateSession(session);
  const options = { ownerId, csrfToken: "csrf", historyContext: captureHistory("csrf"), role: "admin", sql: "DO_NOT_SEND" }, calls = [];
  t.after(clearHistory);
  const saved = readReply(); saved.note.revision++;
  const replies = [library(), readReply(), readReply(), saved, envelope({ deleted: { id: item().id, revision: 3 } }), prepared()];
  t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json(replies.shift(), 200, { "X-Aqua-History-Revision": revision }); });
  await listContextNotes(options); await readContextNote(item(), scope, options); await createContextNote(fields(), scope, requestId, options);
  await saveContextNote(note(), fields(), scope, options); await forgetContextNote(item(), scope, options); await prepareContextNote(note(), scope, options);
  assert.deepEqual(calls.map(call => [call.url, call.init.method]), [
    ["/api/v1/me/context-notes", "GET"], [`/api/v1/me/context-notes/${item().id}`, "GET"], ["/api/v1/me/context-notes", "POST"],
    [`/api/v1/me/context-notes/${item().id}`, "PATCH"], [`/api/v1/me/context-notes/${item().id}/forget`, "POST"], [`/api/v1/me/context-notes/${item().id}/prepare`, "POST"]]);
  assert.equal(calls[0].init.body, undefined); assert.equal(calls[1].init.body, undefined);
  assert.deepEqual(JSON.parse(calls[2].init.body), { schemaVersion: 1, expected_scope_id: scope.id, client_request_id: requestId, ...fields() });
  for (const { init } of calls) {
    assert.equal(init.headers["X-Aqua-History-Revision"], revision); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error");
    assert.equal(init.credentials, "same-origin"); assert.equal(init.body?.includes("DO_NOT_SEND") || false, false);
    if (init.method !== "GET") assert.equal(init.headers["X-CSRF-Token"], "csrf");
  }
});

test("invalid inputs, unavailable body selection and oversized stream fail before displaying content", async t => {
  const fetch = t.mock.method(globalThis, "fetch", async () => json(readReply()));
  await assert.rejects(createContextNote({ ...fields(), role: "admin" }, scope, requestId, { ownerId, csrfToken: "csrf" }), { code: "invalid_input" });
  await assert.rejects(readContextNote(library().items[1], scope, { ownerId }), { code: "invalid_input" });
  assert.equal(fetch.mock.callCount(), 0);
  let cancelled = false; t.mock.method(globalThis, "fetch", async () => new Response(new ReadableStream({ cancel() { cancelled = true; } }), {
    headers: { "Content-Type": "application/json", "Content-Length": "32769" } }));
  await assert.rejects(listContextNotes({ ownerId }), { code: "invalid_response" }); assert.equal(cancelled, true);
});

test("a late real transport reply cannot cross a session or history replacement", async t => {
  clearHistory(); t.after(clearHistory); activateSession({ user: { id: ownerId }, csrf_token: "csrf-a" });
  let release; t.mock.method(globalThis, "fetch", () => new Promise(resolve => { release = resolve; }));
  const pending = listContextNotes({ ownerId, csrfToken: "csrf-a", historyContext: captureHistory("csrf-a") });
  activateSession({ user: { id: otherId }, csrf_token: "csrf-b" }); release(json(library()));
  await assert.rejects(pending, { name: "AbortError" });
});
