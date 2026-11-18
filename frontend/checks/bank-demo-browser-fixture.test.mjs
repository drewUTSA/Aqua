import assert from "node:assert/strict";
import test from "node:test";
import { installBankDemoFixture, bankReportGold, BANK_REPORT_ID } from "./bank-demo-browser-fixture.mjs";
import { decodeBankContext, decodeBankReport } from "../src/features/bankDemo/contract.js";
import { chatRecord, messageRecord } from "../src/services/workspaceContract.js";
import { bankDemoKey, bankDemoChooseFirst, bankDemoDoubledText } from "./bank-demo-browser-checks.mjs";

const ownerA = "7506fb3d-1119-4b29-8c57-5ea696a739a1", ownerB = "25a433e1-8ca6-4e02-a49c-b57aac5983a8";
function setup() {
  const base = { email: "a", session: () => ({ user: { id: base.email === "a" ? ownerA : ownerB } }), route: async (_, reply) => reply(418, { delegated: true }) };
  const state = installBankDemoFixture(base), replies = [];
  const call = async (path = "context", overrides = {}) => {
    const method = path === "reports" ? "POST" : "GET";
    await base.route({ method, url: `http://127.0.0.1:12345/api/v1/bank-demo/${path}`,
      headers: { Origin: "http://127.0.0.1:12345", "X-CSRF-Token": "fixture-session-csrf" }, ...overrides },
    async (status, body, headers) => replies.push({ status, body, headers }));
    return replies.at(-1);
  };
  const post = body => call("reports", { postData: JSON.stringify(body) });
  return { base, state, replies, call, post };
}
const body = revision => ({ schemaVersion: 1, report_id: BANK_REPORT_ID, expected_source_revision: revision });

test("bank native Enter includes its activation character without altering Tab or Escape", async () => {
  const calls = [];
  for (const key of ["Enter", "Tab", "Escape"]) await bankDemoKey((...args) => { calls.push(args); }, key);
  assert.deepEqual(calls, [["Enter", 0, "\r"], ["Tab", 0, undefined], ["Escape", 0, undefined]]);
});
test("native picker uses closed-select arrows and leaves Tab available for the Read button", async () => {
  const keys = []; await bankDemoChooseFirst(key => { keys.push(key); });
  assert.deepEqual(keys, ["Home", "ArrowDown"]);
});
test("doubled text is measured against its actual legible baseline with tight tolerance", () => {
  assert.equal(bankDemoDoubledText(14, 28), true); assert.equal(bankDemoDoubledText(16, 32), true);
  assert.equal(bankDemoDoubledText(14, 28.09), true); assert.equal(bankDemoDoubledText(14, 28.11), false);
  for (const pair of [[13,26],[14,14],[14,27],[14,30],[NaN,28],[14,Infinity],["14",28]]) assert.equal(bankDemoDoubledText(...pair), false);
});

test("all four original projected scopes decode and retain independent owner-bound copies", async () => {
  const { state, call, base } = setup();
  for (const [persona, count] of [["none", 0], ["teller", 2], ["analyst", 4], ["manager", 17]]) {
    state.persona = persona; const value = await call();
    assert.equal(value.status, 200); const context = decodeBankContext(value.body, ownerA);
    assert.equal(context.reports.length, count); assert.equal(context.persona, persona);
    value.body.context.notice = "client-mutated";
    assert.notEqual((await call()).body.context.notice, "client-mutated");
  }
  base.email = "b"; assert.equal((await call()).body.owner_id, ownerB);
});
test("fixture preserves every original deposit cell and procedure while requiring explicit scoped inputs", async () => {
  const { call, post } = setup(); const envelope = (await call()).body;
  const context = decodeBankContext(envelope, ownerA), report = await post(body(context.sourceRevision));
  const decoded = decodeBankReport(report.body, ownerA, BANK_REPORT_ID, context), gold = bankReportGold();
  assert.deepEqual(decoded.rows, gold.rows); assert.deepEqual(decoded.procedure, gold.procedure);
  assert.deepEqual(decoded.rows[0], ["north", "checking", "1200", "1461250.00"]);
  assert.equal(decoded.rowCount, 7); assert.equal(report.body.result.periodComplete, false);
  assert.ok(Buffer.byteLength(JSON.stringify(report.body)) <= 32768);
});
test("browser double refuses client authority, source drift, missing CSRF and nonlocal origins", async () => {
  const { call, post, state } = setup(); const rev = (await call()).body.context.sourceRevision;
  for (const field of ["persona", "tenant", "scope", "rows", "sql"]) assert.equal((await post({ ...body(rev), [field]: "manager" })).status, 422);
  assert.equal((await post(body("d".repeat(64)))).status, 409);
  assert.equal((await call("reports", { postData: JSON.stringify(body(rev)), headers: {} })).status, 403);
  assert.equal((await call("context", { url: "https://aqua-ai.us/api/v1/bank-demo/context" })).status, 403);
  state.persona = "none"; assert.equal((await post(body(rev))).status, 403);
  assert.equal((await call("context?persona=manager")).status, 422);
});
test("disabled, anonymous and one-shot fixed failures remain explicit fixture states", async () => {
  const { state, base, call } = setup(); state.enabled = false;
  assert.equal((await call()).status, 404); state.enabled = true;
  base.email = null; assert.equal((await call()).status, 401); base.email = "a";
  for (const status of [403, 409, 503]) { state.failNext = status; assert.equal((await call()).status, status); assert.equal((await call()).status, 200); }
});
test("held replies retain initiating owner and bound queue, with no token-bearing diagnostics", async () => {
  const { state, base, call, replies } = setup(); state.hold = "context";
  for (let i = 0; i < 4; i++) await call();
  assert.equal(replies.length, 0); assert.equal(state.pending.length, 4);
  assert.equal((await call()).status, 429); assert.equal(state.pending.length, 4);
  base.email = "b"; state.historyRevision = "b".repeat(64); await state.release();
  assert.equal(state.pending.length, 0); assert.equal(state.peakHeld, 4);
  for (const reply of replies.slice(1)) { assert.equal(reply.body.owner_id, ownerA); assert.equal(reply.headers["X-Aqua-History-Revision"], "b".repeat(64)); }
  const diagnostics = JSON.stringify(state.calls);
  assert.ok(!diagnostics.includes("fixture-session-csrf")); assert.ok(!diagnostics.includes("postData"));
});
test("mock request count is finite and unrelated routes keep their original delegate", async () => {
  const { state, call } = setup();
  assert.equal((await call("context", { url: "http://127.0.0.1:12345/api/models" })).status, 418);
  for (let i = 0; i < 80; i++) assert.equal((await call()).status, 200);
  assert.equal((await call()).status, 429); assert.equal(state.calls.length, 80);
});
test("seeded saved contexts have coherent user-only history and never fabricate SQL results", async () => {
  const { call, base } = setup();
  const listing = await call("context", { url: "http://127.0.0.1:12345/api/v1/chats?limit=20" });
  assert.equal(listing.body.items.length, 2);
  for (const item of listing.body.items) {
    const chat = chatRecord(item); assert.equal(chat.messageCount, 1);
    const page = await call("context", { url: `http://127.0.0.1:12345/api/v1/chats/${chat.id}/messages?limit=20` });
    assert.equal(page.body.items.length, chat.messageCount);
    const message = messageRecord(page.body.items[0]);
    assert.equal(message.conversationId, chat.id); assert.equal(message.role, "user"); assert.equal(message.response, null);
    assert.ok(!JSON.stringify(page).includes("SELECT"));
  }
  base.email = null; assert.equal((await call("context", { url: "http://127.0.0.1:12345/api/v1/chats?limit=20" })).status, 401);
});
