import assert from "node:assert/strict";
import test from "node:test";
import { deleteChat, listChats, listMessages, savePrompt, submitQuestion, workspaceRequest } from "../src/services/workspaceClient.js";
import { messageRecord, submissionRecord } from "../src/services/workspaceContract.js";

const A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", C = "cccccccc-cccc-4ccc-8ccc-cccccccccccc", D = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
const chat = { id: A, title: "Private title", project_id: null, archived: false, revision: 1, message_count: 2, last_activity_at: "2026-10-26T12:00:00Z" };
const response = { status: "success", message: "Synthetic answer", model: "gemini", sql: "SELECT 1", tables: [], visualizations: [], kpis: [] };
const input = { id: B, chat_id: A, sequence: 1, role: "user", content: "Synthetic question", request_id: D, reply_to: null, model_id: "gemini", status: "complete", response: null, result_unavailable: false };
const assistant = { ...input, id: C, sequence: 2, role: "aqua", content: "", reply_to: B, response };
const submission = { chat, request: { id: D, client_request_id: D, state: "complete", input_message_id: B, reply_message_id: C }, input_message: input, assistant_message: assistant, response };
const json = (body, status = 200, headers = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });

test("only an available saved reply can offer the validated employee cash confirmation", () => {
  const confirmation = "Confirm cash comparison for today using USD 18.25 available cash and USD 22.07 projected outflows.";
  const offer = { confirmation, source_revision: "c".repeat(64) };
  const saved = { ...assistant, response: { ...response, bank_cash_review: offer } };
  assert.equal(messageRecord(saved).response.cashConfirmation, confirmation);
  const manual = { ...assistant, response: { ...response, bank_cash_reply: true, bank_cash_manual: true } };
  assert.equal(messageRecord(manual).response.cashManual, true);
  for (const changed of [{ ...manual, role: "user" }, { ...manual, result_unavailable: true },
    { ...manual, response: { ...response, bank_cash_manual: true } }]) {
    assert.equal(messageRecord(changed).response?.cashManual, undefined);
  }
  for (const record of [{ ...saved, role: "user" }, { ...saved, result_unavailable: true },
    { ...saved, response: { ...response, bank_cash_review: { ...offer, confirmation: "Approve a transfer" } } },
    { ...saved, response: { ...response, bank_cash_review: { ...offer, source_revision: "" } } }]) {
    assert.equal(messageRecord(record).response?.cashConfirmation, undefined);
  }
});

test("previous-source links belong only to server-authorized unavailable answers", () => {
  const previous = messageRecord({ ...assistant, result_unavailable: true, previous_source_available: true });
  assert.equal(previous.previousSourceAvailable, true);
  assert.equal(previous.response.sql, "");
  assert.equal(previous.response.tables.length, 0);
  assert.equal(messageRecord({ ...input, previous_source_available: true }).previousSourceAvailable, undefined);
  assert.equal(messageRecord({ ...assistant, previous_source_available: true }).previousSourceAvailable, undefined);
});

test("only short analysis submissions use the retry interval as employee-facing copy", async (t) => {
  let header = "3";
  const fetch = t.mock.method(globalThis, "fetch", async () => json({}, 429, { "Retry-After": header }));
  const normal = { csrfToken: "csrf" }, input = { client_request_id: D, question: "Synthetic count" };
  const denied = () => submitQuestion(input, normal);
  await assert.rejects(denied(), { code: "throttled", retryAfter: 3, message: "Try submitting your question again in 3 seconds." });
  header = "1";
  await assert.rejects(denied(), { message: "Try submitting your question again in 1 second." });
  await assert.rejects(listChats(normal), { message: "Too many workspace actions. Wait before trying again." });
  for (const value of ["60", "9999", "garbled"]) {
    header = value;
    await assert.rejects(denied(), { message: "Too many workspace actions. Wait before trying again." });
  }
  assert.equal(fetch.mock.callCount(), 6);
});

test("first durable submit and explicit retry use canonical routes without assistant uploads", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json(submission, 201); });
  const result = await submitQuestion({ client_request_id: D, question: "Synthetic question", model: "gemini" }, { csrfToken: "csrf" });
  assert.equal(result.chat.id, A); assert.equal(result.assistant.replyTo, B); assert.equal(result.assistant.response.sql, "");
  await submitQuestion({ chatId: A, retryInputId: B, client_request_id: D }, { csrfToken: "csrf" });
  assert.deepEqual(calls.map((call) => call.url), ["/api/v1/chats", `/api/v1/chats/${A}/messages/${B}/retries`]);
  assert.deepEqual(JSON.parse(calls[1].init.body), { client_request_id: D });
  for (const { init } of calls) { assert.equal(init.credentials, "same-origin"); assert.equal(init.cache, "no-store");
    assert.equal(init.redirect, "error"); assert.equal(init.headers["X-CSRF-Token"], "csrf"); assert.equal(init.method, "POST"); }
});
test("same operation reference is sent exactly once per explicit replay; no automatic retry", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (_url, init) => { calls.push(JSON.parse(init.body)); throw new Error("secret endpoint"); });
  const body = { client_request_id: D, question: "Synthetic question" };
  await assert.rejects(submitQuestion(body, { csrfToken: "csrf" }), (error) => !error.message.includes("secret"));
  assert.equal(calls.length, 1);
  await assert.rejects(submitQuestion(body, { csrfToken: "csrf" })); assert.deepEqual(calls, [body, body]);
});
test("private title search stays in a CSRF protected POST body and cursors stay bounded", async (t) => {
  const calls = []; t.mock.method(globalThis, "fetch", async (url, init) => { calls.push({ url, init }); return json(url.includes("/messages") ? { items: [input, assistant], older_cursor: "opaque" } : { items: [chat], next_cursor: null }); });
  const search = "<img src=x>&owner_id=other";
  assert.equal((await listChats({ search, cursor: "opaque+/=", csrfToken: "csrf" })).items[0].title, chat.title);
  assert.equal((await listMessages(A)).cursor, "opaque");
  assert.equal(calls[0].url, "/api/v1/chats/search"); assert.equal(calls[0].init.method, "POST");
  assert.equal(calls[0].init.headers["X-CSRF-Token"], "csrf");
  assert.deepEqual(JSON.parse(calls[0].init.body), { search, archived: false, limit: 20, cursor: "opaque+/=" });
  assert.equal(calls.some((call) => call.url.includes(search) || call.url.includes("owner_id")), false);
  await listChats({ search: "", cursor: "opaque+/=" });
  assert.equal(calls[2].init.method, "GET"); assert.equal(new URL(calls[2].url, "https://fixture.invalid").searchParams.has("search"), false);
});
test("mutations require CSRF and resource IDs cannot become paths or hosts", async (t) => {
  const fetch = t.mock.method(globalThis, "fetch", async () => { throw new Error("network must not run"); });
  await assert.rejects(savePrompt(null, { label: "A", prompt: "B" }), { code: "unauthenticated" });
  assert.throws(() => listMessages("//attacker.invalid"), { code: "invalid_input" });
  assert.equal(fetch.mock.callCount(), 0);
});
for (const [status, code] of [[401, "unauthenticated"], [403, "forbidden"], [404, "not_found"], [409, "conflict"], [429, "throttled"], [503, "unavailable"]]) {
  test(`workspace HTTP ${status} gives fixed safe feedback without server text`, async (t) => {
    const fetch = t.mock.method(globalThis, "fetch", async () => json({ error: { message: "private-secret", owner: "other" } }, status, { "Retry-After": "60" }));
    await assert.rejects(listChats(), (error) => error.code === code && !JSON.stringify(error).includes("private-secret") && !error.message.includes("private-secret"));
    assert.equal(fetch.mock.callCount(), 1);
  });
}
test("oversized or malformed workspace payloads never become rendered state", async (t) => {
  t.mock.method(globalThis, "fetch", async () => json({ items: Array(101).fill(chat), next_cursor: null }));
  await assert.rejects(listChats(), { code: "invalid_response" });
  t.mock.method(globalThis, "fetch", async () => json({}, 200, { "Content-Length": String(6 * 1024 * 1024 + 1) }));
  await assert.rejects(listChats(), { code: "invalid_response" });
  assert.throws(() => submissionRecord({ ...submission, assistant_message: { ...assistant, chat_id: B } }), /workspace_invalid_response/);
});
test("bounded history accepts twenty near-limit saved results without rejecting a valid page", async (t) => {
  const items = Array.from({ length: 20 }, (_, index) => ({ ...assistant, sequence: index + 1, response: { ...response, message: "x".repeat(235000) } }));
  t.mock.method(globalThis, "fetch", async () => json({ items, older_cursor: null }));
  const page = await listMessages(A); assert.equal(page.items.length, 20); assert.equal(page.items[19].response.message.length, 235000);
});
test("historical grant denial shows no saved SQL, tables or result text", () => {
  const denied = messageRecord({ ...assistant, result_unavailable: true, response });
  assert.equal(denied.response.error.code, "access_denied"); assert.equal(denied.response.sql, "");
  assert.deepEqual(denied.response.tables, []); assert.equal(JSON.stringify(denied.response).includes("Synthetic answer"), false);
});
test("mismatched operation or chat references cannot replace the requested history", async (t) => {
  t.mock.method(globalThis, "fetch", async () => json({ ...submission, request: { ...submission.request, client_request_id: B } }));
  await assert.rejects(submitQuestion({ client_request_id: D, question: "A" }, { csrfToken: "csrf" }), { code: "invalid_response" });
  t.mock.method(globalThis, "fetch", async () => json({ items: [{ ...input, chat_id: B }], older_cursor: null }));
  await assert.rejects(listMessages(A), { code: "invalid_response" });
});
test("delete is never confirmed from an unexpected success status", async (t) => {
  t.mock.method(globalThis, "fetch", async () => json({ okay: true }, 200));
  await assert.rejects(deleteChat(A, 1, { csrfToken: "csrf" }));
});
test("abort prevents stale workspace completion and does not resubmit", async (t) => {
  const controller = new AbortController(); const fetch = t.mock.method(globalThis, "fetch", async () => { controller.abort(); return json(submission); });
  await assert.rejects(submitQuestion({ client_request_id: D, question: "A" }, { csrfToken: "csrf", signal: controller.signal }), { name: "AbortError" });
  assert.equal(fetch.mock.callCount(), 1);
});
