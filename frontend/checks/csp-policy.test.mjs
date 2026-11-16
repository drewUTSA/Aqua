import assert from "node:assert/strict";
import test from "node:test";
import { readFileSync } from "node:fs";
import { documentPolicyHeaders, loadDocumentPolicies, readDocumentPolicies } from "./csp-policy.mjs";
import { browserFixtureMode, staticFixtureResponse, SECURE_ACCOUNT_ORIGIN } from "./p10b-browser-mode.mjs";

const source = readFileSync(new URL("../nginx.conf", import.meta.url), "utf8");
test("source CSP enforces only the document baseline and keeps the full candidate report-only", () => {
  const policies = loadDocumentPolicies(), headers = documentPolicyHeaders();
  assert.match(policies.sha256, /^[a-f0-9]{64}$/);
  assert.deepEqual(headers.map(header => header.name), ["Content-Security-Policy", "Content-Security-Policy-Report-Only"]);
  assert.equal(headers[0].value, policies.enforced); assert.equal(headers[1].value, policies.reportOnly);
  assert.ok(!headers[0].value.includes("script-src")); assert.ok(headers[1].value.includes("script-src 'self' https://accounts.google.com/gsi/client"));
  assert.doesNotMatch(headers.map(header => header.value).join(";"), /unsafe-eval|report-uri|report-to|report-sample/);
  assert.equal(Object.isFrozen(policies), true);
});
test("changed script authority or telemetry cannot enter through the source policy projection", () => {
  for (const changed of [source.replaceAll("https://accounts.google.com/gsi/client", "https://accounts.google.com/"),
    source.replaceAll("script-src 'self'", "script-src 'self' 'unsafe-eval'"), source.replaceAll("manifest-src 'self'", "report-uri /collect; manifest-src 'self'"),
    source.replace("object-src 'none'; base-uri 'none'; frame-ancestors 'none'", "object-src 'self'; base-uri 'none'; frame-ancestors 'none'"),
    source.replace("add_header Content-Security-Policy-Report-Only", "add_header Content-Security-Policy")]) assert.throws(() => readDocumentPolicies(changed), /document_csp_invalid/);
});
test("enforcement is a closed explicit fixture option with no caller policy or live origin", () => {
  assert.deepEqual(browserFixtureMode({ cspEnforcedFixture: true }), { secureAccountFixture: false, cspEnforcedFixture: true });
  for (const options of [{ cspEnforcedFixture: "true" }, { cspEnforcedFixture: 1 }, { cspEnforcedFixture: true, policy: "default-src *" },
    Object.defineProperty({}, "cspEnforcedFixture", { get() { throw Error("getter evaluated"); }, enumerable: true })]) assert.throws(() => browserFixtureMode(options), /fixture_mode_invalid/);
  assert.throws(() => documentPolicyHeaders("live"), /document_csp_mode_invalid/);
  assert.throws(() => documentPolicyHeaders("enforced-fixture", { enforced: "default-src *", reportOnly: "default-src *" }), /document_csp_invalid/);
  const headers = documentPolicyHeaders("enforced-fixture"); assert.equal(headers.length, 1);
  assert.equal(headers[0].value, loadDocumentPolicies().reportOnly);
});
test("secure document responses carry the same policy while scripts and API responses get no competing CSP", () => {
  const files = new Map([["/index.html", Buffer.from("synthetic app")], ["/assets/code.js", Buffer.from("code")]]);
  for (const mode of ["source", "enforced-fixture"]) {
    const document = staticFixtureResponse(files, new URL("/settings", SECURE_ACCOUNT_ORIGIN), mode);
    assert.deepEqual(document.headers.filter(header => header.name.startsWith("Content-Security-Policy")), documentPolicyHeaders(mode));
    for (const route of ["/assets/code.js", "/api/auth/google/redirect"]) {
      const reply = staticFixtureResponse(files, new URL(route, SECURE_ACCOUNT_ORIGIN), mode);
      assert.equal(reply.headers.some(header => header.name.startsWith("Content-Security-Policy")), false);
    }
  }
});
