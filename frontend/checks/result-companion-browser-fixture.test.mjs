import assert from "node:assert/strict";
import test from "node:test";
import { installResultCompanionFixture, RESULT_CHAT_TITLES, RESULT_BROWSER_GOLD } from "./result-companion-browser-fixture.mjs";
import { chatRecord, messageRecord } from "../src/services/workspaceContract.js";
import { resultBinding } from "../src/features/resultCompanion/binding.js";
import { decodeResultBrief } from "../src/features/resultCompanion/contract.js";

const ownerA = "7506fb3d-1119-4b29-8c57-5ea696a739a1", ownerB = "25a433e1-8ca6-4e02-a49c-b57aac5983a8";
function setup() {
  const base = { email: "a", canQuery: true, session: () => ({ user: { id: base.email === "a" ? ownerA : ownerB } }), route: async (_, reply) => reply(418, { delegated: true }) };
  const state = installResultCompanionFixture(base), replies = [];
  const call = async (path = "/api/v1/companion/result-brief", override = {}) => {
    const before = replies.length;
    await base.route({ url: `http://127.0.0.1:12345${path}`, method: "GET",
      headers: { Origin: "http://127.0.0.1:12345", "X-CSRF-Token": "fixture-session-csrf" }, ...override },
    async (status, body, headers) => replies.push({ status, body, headers }));
    return replies.length > before ? replies.at(-1) : null;
  };
  const post = (request, index = 0, extra = {}, override = {}) => call(undefined, { method: "POST", postData: JSON.stringify({ schemaVersion: 1, request_id: request, column_index: index, ...extra }), ...override });
  return { base, state, replies, call, post };
}
async function saved(f, index = 0) {
  const listing = await f.call("/api/v1/chats?limit=20"), chat = chatRecord(listing.body.items[index]);
  const page = await f.call(`/api/v1/chats/${chat.id}/messages?limit=20`), messages = page.body.items.map(messageRecord);
  const binding = resultBinding({ durable: true, activeConversationId: chat.id, active: {}, messages }, ownerA, messages[1].id, true);
  return { chat, messages, binding, request: messages[1].requestId };
}

test("two synthetic saved histories have coherent durable links and exact sidecar provenance", async () => {
  const f = setup();
  for (let index = 0; index < 2; index++) {
    const value = await saved(f, index); assert.equal(value.chat.title, RESULT_CHAT_TITLES[index]); assert.equal(value.chat.messageCount, 2);
    assert.equal(value.messages[1].replyTo, value.messages[0].id); assert.ok(value.binding);
    const result = await f.post(value.request), decoded = decodeResultBrief(result.body, value.binding, 0);
    assert.equal(decoded.brief.numeric.maximum.value, RESULT_BROWSER_GOLD.maximum);
    assert.equal(decoded.brief.numeric.minimum.value, RESULT_BROWSER_GOLD.minimum);
    assert.deepEqual(decoded.brief.numeric.minimum.witness_rows, [1, 3]); assert.equal(decoded.brief.counts.missing_values, 1);
    assert.equal(decoded.brief.source.freshness_at, null); assert.equal(decoded.brief.field.unit, null);
  }
});

test("selected text projection retains numeric-looking strings as text with no invented extrema", async () => {
  const f = setup(), value = await saved(f), result = await f.post(value.request, 1);
  const brief = decodeResultBrief(result.body, value.binding, 1).brief;
  assert.equal(brief.field.kind, "text"); assert.equal(brief.numeric, null); assert.equal(brief.counts.missing_values, 0);
  assert.deepEqual(brief.followup_intents, ["verify_scope"]); assert.equal(value.binding.table.rows[0].tag, "1000");
});

test("double refuses uploaded rows, role claims, invalid identity/index, missing CSRF and external origins", async () => {
  const f = setup(), { request } = await saved(f);
  for (const key of ["owner_id", "tenant", "role", "rows", "sql", "source", "url"]) assert.equal((await f.post(request, 0, { [key]: "CANARY" })).status, 422);
  for (const index of [true, 0.5, -1, 2]) assert.equal((await f.post(request, index)).status, 422);
  assert.equal((await f.post("00000000-0000-4000-8000-000000000000")).status, 404);
  assert.equal((await f.post(request, 0, {}, { headers: {} })).status, 403);
  assert.equal((await f.post(request, 0, {}, { url: "https://aqua-ai.us/api/v1/companion/result-brief" })).status, 403);
  assert.equal((await f.call("/api/v1/companion/result-brief?role=admin", { method: "POST" })).status, 422);
  assert.equal((await f.post(request, 0, {}, { postData: "x".repeat(8193) })).status, 413);
  assert.equal((await f.post(request, 0, {}, { postData: "{malformed" })).status, 422);
});

test("disabled, denied and fixed transient failures remain separate without reflected input", async () => {
  const f = setup(), { request } = await saved(f); f.state.enabled = false;
  assert.equal((await f.post(request)).status, 404); f.state.enabled = true; f.base.canQuery = false;
  assert.equal((await f.post(request)).status, 403);
  const page = await f.call(`/api/v1/chats/${(await saved(f)).chat.id}/messages`);
  assert.equal(page.body.items[1].result_unavailable, true); assert.equal(page.body.items[1].response, null);
  f.base.canQuery = true; f.base.email = null; assert.equal((await f.post(request)).status, 401); f.base.email = "a";
  for (const status of [403, 409, 503]) { f.state.failNext = status; assert.equal((await f.post(request)).status, status); assert.equal((await f.post(request)).status, 200); }
});

test("held replies bind the initiating owner, cap four holds and retain metadata-only diagnostics", async () => {
  const f = setup(), { request } = await saved(f); f.state.hold = true;
  for (let i = 0; i < 4; i++) assert.equal(await f.post(request), null);
  assert.equal((await f.post(request)).status, 429); assert.equal(f.state.pending.length, 4);
  f.base.email = "b"; f.state.historyRevision = "b".repeat(64); await f.state.release();
  for (const item of f.replies.slice(-4)) { assert.equal(item.body.owner_id, ownerA); assert.equal(item.headers["X-Aqua-History-Revision"], "b".repeat(64)); }
  assert.equal(f.state.pending.length, 0); assert.equal(f.state.peakHeld, 4);
  assert.equal((await f.post(request)), null); f.state.hold = false; await f.state.release();
  assert.equal(f.replies.at(-1).body.owner_id, ownerB);
  assert.ok(!JSON.stringify(f.state.calls).includes("postData")); assert.ok(!JSON.stringify(f.state.calls).includes("csrf"));
});

test("fixed brief-call cap never changes unrelated route delegation", async () => {
  const f = setup(), { request } = await saved(f);
  assert.equal((await f.call("/api/models")).status, 418);
  for (let i = 0; i < 80; i++) assert.equal((await f.post(request)).status, 200);
  assert.equal((await f.post(request)).status, 429); assert.equal(f.state.calls.length, 80);
});
