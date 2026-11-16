import assert from "node:assert/strict";
import test from "node:test";
import { installCompanionToolsFixture } from "./companion-tools-fixture.mjs";

function setup() {
  let forwards = 0;
  const base = { email: "synthetic@example.test", canQuery: true, async route() { forwards++; } };
  const help = installCompanionToolsFixture(base), replies = [];
  const request = async (path, method = "GET", body, headers = {}) => {
    await base.route({ url: "http://127.0.0.1:9999" + path, method, headers: { Origin: "http://127.0.0.1:9999", "X-CSRF-Token": "fixture-session-csrf", ...headers },
      ...(body ? { postData: JSON.stringify(body) } : {}) }, async (status, value, extra) => { replies.push({ status, value, extra }); });
    return replies.at(-1);
  };
  return { base, help, replies, request, forwards: () => forwards };
}

test("opt-in helper intercepts only its two closed paths and stores method/path counts", async () => {
  const value = setup();
  await value.request("/api/auth/me"); assert.equal(value.forwards(), 1);
  const menu = await value.request("/api/v1/companion/capabilities");
  assert.deepEqual(menu.value.capabilities.map((item) => item.id), ["app_help", "authorized_question"]);
  const result = await value.request("/api/v1/companion/help", "POST", { schemaVersion: 1, question: "PRIVATE-QUESTION-CANARY" });
  assert.equal(result.value.method, "reviewed_lookup"); assert.equal(result.value.citations.length, 1);
  assert.equal(JSON.stringify(value.help.calls).includes("PRIVATE-QUESTION"), false);
  assert.equal(value.forwards(), 1);
});

test("disabled feature, revoked fixture identity and denied question capability are distinct", async () => {
  const value = setup(); value.help.enabled = false;
  assert.equal((await value.request("/api/v1/companion/capabilities")).status, 404);
  value.help.enabled = true; value.help.allowQuestion = false;
  assert.deepEqual((await value.request("/api/v1/companion/capabilities")).value.capabilities, [{ id: "app_help", behavior: "reviewed_lookup" }]);
  value.base.email = null;
  assert.equal((await value.request("/api/v1/companion/capabilities")).status, 401);
});

test("synthetic malformed/foreign inputs do not become arbitrary writes or responses", async () => {
  const value = setup(), body = { schemaVersion: 1, question: "charts" };
  assert.equal((await value.request("/api/v1/companion/help", "POST", body, { Origin: "https://foreign.invalid" })).status, 403);
  assert.equal((await value.request("/api/v1/companion/help", "POST", { ...body, sql: "SELECT 1" })).status, 422);
  assert.equal((await value.request("/api/v1/companion/help", "POST", { ...body, question: "x".repeat(2001) })).status, 422);
  assert.equal((await value.request("/api/v1/companion/capabilities?question=private")).status, 422);
  assert.equal((await value.request("/api/v1/companion/execute", "POST", body)).status, 404);
  assert.equal(value.forwards(), 0);
});

test("held answers are bounded, preserve their own response and release without background work", async () => {
  const value = setup(); value.help.hold = true; value.help.replyText = "OLDER";
  await value.request("/api/v1/companion/help", "POST", { schemaVersion: 1, question: "first" });
  value.help.replyText = "NEWER";
  for (let n = 1; n < 8; n++) await value.request("/api/v1/companion/help", "POST", { schemaVersion: 1, question: "later" });
  assert.equal(value.help.pending.length, 8);
  assert.equal((await value.request("/api/v1/companion/help", "POST", { schemaVersion: 1, question: "overflow" })).status, 429);
  await value.help.release(); assert.equal(value.help.pending.length, 0);
  assert.equal(value.replies[1].value.message, "OLDER"); assert.equal(value.replies[2].value.message, "NEWER");
});
