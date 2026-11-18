import assert from "node:assert/strict";
import test from "node:test";
import { installContextNotesFixture, NOTE_IDS, NOTE_CHAT_TITLES, NOTES_GOLD } from "./p05-context-notes-fixture.mjs";
import { decodeNoteList, decodeNote, decodePreparedNote, decodeForgottenNote } from "../src/features/contextNotes/contract.js";
import { chatRecord, messageRecord } from "../src/services/workspaceContract.js";

const ownerA = "7506fb3d-1119-4b29-8c57-5ea696a739a1", ownerB = "25a433e1-8ca6-4e02-a49c-b57aac5983a8";
const createId = "56000000-0000-4000-8000-000000000001", root = "/api/v1/me/context-notes";
function setup() {
  const base = { email: "a", canQuery: true, session: () => ({ user: { id: base.email === "a" ? ownerA : ownerB } }),
    route: async (_, reply) => reply(418, { delegated: true }) };
  const state = installContextNotesFixture(base), replies = [];
  const call = async (path = root, options = {}) => {
    const before = replies.length;
    await base.route({ url: `http://127.0.0.1:12345${path}`, method: "GET",
      headers: { Origin: "http://127.0.0.1:12345", "X-CSRF-Token": "fixture-session-csrf" }, ...options },
    async (status, body, headers) => replies.push({ status, body, headers }));
    return replies.length > before ? replies.at(-1) : null;
  };
  const write = (path, body, method = "POST", options = {}) => call(path, { method, postData: JSON.stringify(body), ...options });
  return { base, state, replies, call, write };
}
async function listing(f) { return decodeNoteList((await f.call()).body, f.base.email === "a" ? ownerA : ownerB); }
const fields = { kind: "note", label: NOTES_GOLD.newLabel, body: NOTES_GOLD.newBody };
const create = scope => ({ schemaVersion: 1, client_request_id: createId, expected_scope_id: scope.id, ...fields });
const revision = (scope, value) => ({ schemaVersion: 1, expected_scope_id: scope.id, revision: value });

test("metadata list reveals no bodies and explicit read/prepare preserve exact authored bytes", async () => {
  const f = setup(), list = await listing(f), selected = list.items.find(item => item.id === NOTE_IDS.first);
  assert.equal(list.items.length, 3); assert.equal(f.state.calls.filter(call => call.action === "read").length, 0);
  assert.ok(!JSON.stringify(list).includes(NOTES_GOLD.body));
  const unavailable = list.items.find(item => item.id === NOTE_IDS.unavailable);
  assert.deepEqual(unavailable, { id: NOTE_IDS.unavailable, revision: 4, availability: "unavailable", label: "Unavailable saved context", kind: null, created_at: null, updated_at: null });
  const read = decodeNote((await f.call(`${root}/${selected.id}`)).body, ownerA, list.scope, selected);
  assert.equal(read.note.body, NOTES_GOLD.body);
  const prepared = decodePreparedNote((await f.write(`${root}/${selected.id}/prepare`, revision(list.scope, selected.revision))).body, ownerA, list.scope, read.note);
  assert.equal(prepared.draft, NOTES_GOLD.body); assert.equal(prepared.execution_enabled, false);
  read.note.body = "CLIENT MUTATION"; assert.equal((await f.call(`${root}/${selected.id}`)).body.note.body, NOTES_GOLD.body);
});

test("create is explicit and idempotent, full CAS correction advances once, and tombstones block replay", async () => {
  const f = setup(), list = await listing(f), body = create(list.scope);
  const first = await f.write(root, body); assert.equal(first.status, 201);
  const note = decodeNote(first.body, ownerA, list.scope, null, fields).note;
  assert.equal((await f.write(root, body)).status, 200);
  assert.equal((await f.write(root, { ...body, body: "DIFFERENT" })).status, 409);
  const update = { ...revision(list.scope, note.revision), ...fields, body: NOTES_GOLD.correction };
  const saved = await f.write(`${root}/${note.id}`, update, "PATCH");
  assert.equal(saved.status, 200); assert.equal(saved.body.note.revision, note.revision + 1); assert.equal(saved.body.note.body, NOTES_GOLD.correction);
  assert.equal((await f.write(`${root}/${note.id}`, update, "PATCH")).status, 409);
  const forgotten = await f.write(`${root}/${note.id}/forget`, revision(list.scope, saved.body.note.revision));
  decodeForgottenNote(forgotten.body, ownerA, list.scope, saved.body.note);
  assert.ok(!JSON.stringify(forgotten.body).includes(NOTES_GOLD.correction));
  assert.equal((await f.call(`${root}/${note.id}`)).status, 404);
  assert.equal((await f.write(root, body)).status, 409);
});

test("unavailable owned entries support explicit forget without exposing earlier contents or needing query access", async () => {
  const f = setup(); await listing(f); f.base.canQuery = false;
  const list = await listing(f); assert.equal(list.scope.can_use, false);
  assert.ok(list.items.every(item => item.availability === "unavailable" && item.kind === null));
  assert.equal((await f.call(`${root}/${NOTE_IDS.first}`)).status, 403);
  const selected = list.items.find(item => item.id === NOTE_IDS.unavailable);
  const result = await f.write(`${root}/${selected.id}/forget`, revision(list.scope, selected.revision));
  decodeForgottenNote(result.body, ownerA, list.scope, selected);
  assert.equal((await listing(f)).items.some(item => item.id === selected.id), false);
});

test("namespace rejects malformed IDs, authority fields, body shapes and noncanonical typed values", async () => {
  const f = setup(), list = await listing(f), body = create(list.scope);
  for (const client_request_id of [[createId], { id: createId }, null, 1, true, "5600000A-0000-4000-8000-000000000001", "not-a-uuid"])
    assert.equal((await f.write(root, { ...body, client_request_id })).status, 422);
  for (const key of ["owner_id", "dataset", "grant", "scope", "sql", "url", "rows", "execution_enabled"])
    assert.equal((await f.write(root, { ...body, [key]: "PRIVATE CANARY" })).status, 422);
  for (const value of [true, 0, -1, 1.1, Number.MAX_SAFE_INTEGER + 1])
    assert.equal((await f.write(`${root}/${NOTE_IDS.first}/prepare`, revision(list.scope, value))).status, 422);
  for (const value of [null, [], "text", 1]) assert.equal((await f.call(root, { method: "POST", postData: JSON.stringify(value) })).status, 422);
  assert.equal((await f.call(`${root}?owner=other`)).status, 422);
  assert.equal((await f.call(`${root}/not-a-uuid`)).status, 422);
  assert.equal((await f.call(`${root}/${NOTE_IDS.first}/execute`, { method: "POST" })).status, 422);
  assert.equal((await f.call(root, { method: "PUT" })).status, 422);
  assert.equal((await f.call(root, { postData: "{}" })).status, 422);
  assert.equal((await f.call(root, { method: "POST", postData: "x".repeat(8193) })).status, 413);
  assert.equal((await f.call(root, { method: "POST", postData: { ...body } })).status, 422);
  assert.equal((await f.call(root, { method: "POST", postData: '{"schemaVersion":1,"schemaVersion":1}' })).status, 422);
  assert.equal((await f.call(root, { method: "POST", postData: "{broken" })).status, 422);
  assert.equal((await f.write(root, { ...body, schemaVersion: true })).status, 422);
});

test("text and byte limits reject hidden/control labels and retain legitimate multiline body separators", async () => {
  for (const changes of [{ label: " bad" }, { label: "bad\nlabel" }, { label: "bad\u2028label" }, { label: "bad\u2029label" },
    { label: "x".repeat(121) }, { body: "bad\rbody" }, { body: "bad\u007fbody" }, { body: "bad\u0085body" }, { body: "bad\u200bbody" },
    { body: "bad\ud800body" }, { body: " " }, { body: "x".repeat(2001) }, { body: "é".repeat(1025) }]) {
    const f = setup(), list = await listing(f);
    assert.equal((await f.write(root, { ...create(list.scope), ...changes })).status, 422);
  }
  const f = setup(), list = await listing(f), body = "Exact\ttext\nwith\u2028separators\u2029";
  assert.equal((await f.write(root, { ...create(list.scope), body })).body.note.body, body);
});

test("fresh owner, CSRF, origin, scope and history checks do not reflect rejected secrets", async () => {
  const f = setup(), list = await listing(f), body = create(list.scope);
  assert.equal((await f.write(root, body, "POST", { headers: {} })).status, 403);
  assert.equal((await f.write(root, body, "POST", { headers: { Origin: "https://foreign.invalid", "X-CSRF-Token": "fixture-session-csrf" } })).status, 403);
  assert.equal((await f.call(root, { url: "https://aqua-ai.us" + root })).status, 403);
  assert.equal((await f.write(root, { ...body, expected_scope_id: "PRIVATE CANARY" })).status, 409);
  assert.ok(!JSON.stringify(f.replies.at(-1)).includes("PRIVATE CANARY"));
  f.state.requiredHistoryRevision = "a".repeat(64); assert.equal((await f.call()).status, 409);
  assert.equal((await f.call(root, { headers: { "X-Aqua-History-Revision": "a".repeat(64) } })).status, 200);
  f.state.requiredHistoryRevision = null; f.state.scopeEpoch++;
  assert.equal((await f.call(`${root}/${NOTE_IDS.first}`)).status, 404);
  assert.equal((await f.write(root, body)).status, 409);
  f.base.email = "b"; assert.equal((await listing(f)).items.length, 0);
  assert.equal((await f.call(`${root}/${NOTE_IDS.first}`)).status, 404);
  f.base.email = null; assert.equal((await f.call()).status, 401);
});

test("one-shot failures are consumed once and an accepted uncertain write is reconciled without replay", async () => {
  const f = setup(), list = await listing(f);
  f.state.enabled = false; assert.equal((await f.call()).status, 404); f.state.enabled = true;
  for (const status of [403, 409, 503]) { f.state.failNext = status; assert.equal((await f.call()).status, status); assert.equal((await f.call()).status, 200); }
  f.state.failAfterWrite = true;
  assert.equal((await f.write(root, create(list.scope))).status, 503);
  assert.equal(f.state.calls.filter(call => call.action === "create").length, 1);
  assert.ok((await listing(f)).items.some(item => item.id === NOTE_IDS.created));
  assert.equal((await f.call(`${root}/${NOTE_IDS.created}`)).body.note.body, NOTES_GOLD.newBody);
});

test("held responses preserve initiating owner and snapshot while bounding the queue at four", async () => {
  const f = setup(); await listing(f); f.state.hold = "read";
  for (let i = 0; i < 4; i++) assert.equal(await f.call(`${root}/${NOTE_IDS.first}`), null);
  assert.equal((await f.call(`${root}/${NOTE_IDS.first}`)).status, 429);
  f.base.email = "b"; f.state.responseHistoryRevision = "b".repeat(64); await f.state.release();
  for (const result of f.replies.slice(-4)) { assert.equal(result.body.owner_id, ownerA); assert.equal(result.body.note.body, NOTES_GOLD.body); assert.equal(result.headers["X-Aqua-History-Revision"], "b".repeat(64)); }
  assert.equal(f.state.pending.length, 0); assert.equal(f.state.peakHeld, 4);
  const diagnostics = JSON.stringify(f.state.calls); assert.ok(!diagnostics.includes("postData")); assert.ok(!diagnostics.includes("fixture-session-csrf")); assert.ok(!diagnostics.includes(NOTES_GOLD.body));
});

test("request ceiling is finite and unrelated API routes keep their original delegate", async () => {
  const f = setup(); assert.equal((await f.call("/api/models")).status, 418);
  for (let i = 0; i < 80; i++) assert.equal((await f.call()).status, 200);
  assert.equal((await f.call()).status, 429); assert.equal(f.state.calls.length, 80);
});

test("two original saved histories have coherent durable links and no live analysis", async () => {
  const f = setup(), page = await f.call("/api/v1/chats?limit=20");
  for (const [index, raw] of page.body.items.entries()) {
    const chat = chatRecord(raw); assert.equal(chat.title, NOTE_CHAT_TITLES[index]);
    const messages = (await f.call(`/api/v1/chats/${chat.id}/messages?limit=20`)).body.items.map(messageRecord);
    assert.equal(messages[1].replyTo, messages[0].id); assert.equal(messages[1].requestId, messages[0].requestId);
    assert.equal(messages[1].response.tables[0].rows[0].count, 3);
  }
  assert.equal(f.state.calls.length, 0);
});


test("a grant transition rejects the old prepare scope before access and exposes generic metadata only", async () => {
  const f = setup(), list = await listing(f);
  f.base.canQuery = false;
  const denied = await f.write(`${root}/${NOTE_IDS.first}/prepare`, revision(list.scope, 2));
  assert.equal(denied.status, 409);
  assert.ok(!JSON.stringify(denied).includes(NOTES_GOLD.body));
  const current = await listing(f);
  assert.equal(current.scope.can_use, false);
  assert.notEqual(current.scope.id, list.scope.id);
  for (const item of current.items) {
    assert.equal(item.availability, "unavailable");
    assert.equal(item.kind, null);
    assert.ok(!Object.hasOwn(item, "body"));
  }
  assert.equal((await f.write(`${root}/${NOTE_IDS.first}/prepare`, revision(current.scope, 2))).status, 403);
  assert.equal(f.state.calls.filter(call => call.action === "prepare").length, 2);
});
