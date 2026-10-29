import assert from "node:assert/strict";
import test from "node:test";
import { browserFixtureMode, SECURE_ACCOUNT_ORIGIN, staticFixtureResponse } from "./p10b-browser-mode.mjs";
test("secure account browser mode is explicit, boolean and rejects caller-selected origins", () => {
  assert.deepEqual(browserFixtureMode(), { secureAccountFixture: false });
  assert.deepEqual(browserFixtureMode({}), { secureAccountFixture: false });
  assert.deepEqual(browserFixtureMode({ secureAccountFixture: false }), { secureAccountFixture: false });
  assert.deepEqual(browserFixtureMode({ secureAccountFixture: true }), { secureAccountFixture: true });
  assert.equal(SECURE_ACCOUNT_ORIGIN, "https://aqua-browser.example.test");
  for (const options of [true, "true", null, [], { origin: "https://aqua-ai.us" }, { secureAccountFixture: "true" },
    { secureAccountFixture: true, origin: "https://aqua-ai.us" }, Object.defineProperty({}, "secureAccountFixture", { get() { throw Error("must not evaluate"); }, enumerable: true })]) assert.throws(() => browserFixtureMode(options), /fixture_mode_invalid/);
});
test("reserved secure static responses serve only frozen bytes with safe headers and no fallback network", () => {
  const files = new Map([["/index.html", Buffer.from("synthetic app")], ["/assets/code.js", Buffer.from("synthetic code")]]);
  for (const [route, expected] of [["/", "synthetic app"], ["/settings", "synthetic app"], ["/assets/code.js", "synthetic code"]]) {
    const reply = staticFixtureResponse(files, new URL(route, SECURE_ACCOUNT_ORIGIN));
    assert.equal(reply.status, 200); assert.equal(Buffer.from(reply.body, "base64").toString(), expected);
    assert.equal(reply.headers.find(header => header.name === "X-Content-Type-Options").value, "nosniff");
    assert.equal(reply.headers.find(header => header.name === "Cache-Control").value, "no-store");
  }
  assert.equal(staticFixtureResponse(files, new URL("/missing.js", SECURE_ACCOUNT_ORIGIN)).status, 404);
  assert.equal(staticFixtureResponse(files, new URL("/favicon.ico", SECURE_ACCOUNT_ORIGIN)).status, 204);
  assert.equal(staticFixtureResponse(files, new URL("/api/v1/me", SECURE_ACCOUNT_ORIGIN)).status, 404);
  assert.throws(() => staticFixtureResponse(files, new URL("https://aqua-ai.us/")), /secure_static_origin_invalid/);
});
