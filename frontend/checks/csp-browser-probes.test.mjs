import assert from "node:assert/strict";
import test from "node:test";
import { assertCspCoverage, createCspDiagnostics, observeCspBinding } from "./csp-browser-probes.mjs";
const digest = "a".repeat(64);
const event = (directive, phase = "application", disposition = "enforce") => JSON.stringify({ directive, phase, disposition });

test("CSP observations preserve only fixed categories and reject raw sensitive diagnostic fields", () => {
  const state = createCspDiagnostics("source", digest);
  observeCspBinding(state, event("style-src-elem", "application", "report"));
  assert.equal(state.application.report["style-src-elem"], 1);
  assert.throws(() => assertCspCoverage(state), /unexpected_application_csp_violation/);
  for (const payload of [JSON.stringify({ directive: "img-src", phase: "application", disposition: "enforce", blockedURI: "https://private.invalid/?token=SECRET" }),
    event("https://private.invalid/?token=SECRET"), event("script-src", "unknown"), event("script-src", "application", "unknown"), "SECRET".repeat(100), "null"]) {
    const rejected = createCspDiagnostics("source", digest); observeCspBinding(rejected, payload);
    assert.equal(rejected.invalid, true); assert.equal(JSON.stringify(rejected).includes("SECRET"), false);
    assert.throws(() => assertCspCoverage(rejected), /unexpected_application_csp_violation/);
  }
});
test("deliberate canaries never forgive unexpected application violations", () => {
  const state = createCspDiagnostics("enforced-fixture", digest);
  for (const directive of ["script-src", "script-src-elem", "script-src-attr", "connect-src", "img-src", "frame-src", "object-src", "base-uri"]) observeCspBinding(state, event(directive, "canary"));
  state.canaries_completed = true; state.probe_script_requests = 1;
  assert.doesNotThrow(() => assertCspCoverage(state, { canaries: true }));
  const repeated = structuredClone(state); observeCspBinding(repeated, event("script-src", "canary"));
  assert.throws(() => assertCspCoverage(repeated, { canaries: true }), /csp_canary_coverage_invalid/);
  observeCspBinding(state, event("script-src-elem"));
  assert.throws(() => assertCspCoverage(state, { canaries: true }), /unexpected_application_csp_violation/);
});
test("missing or repeated probes, source-mode canaries and excessive diagnostics fail closed", () => {
  const state = createCspDiagnostics("enforced-fixture", digest);
  assert.throws(() => assertCspCoverage(state, { canaries: true }), /csp_canary_coverage_invalid/);
  const source = createCspDiagnostics("source", digest); observeCspBinding(source, event("script-src", "canary")); assert.equal(source.invalid, true);
  for (let count = 0; count < 257; count++) observeCspBinding(state, event("script-src", "canary"));
  assert.equal(state.invalid, true); assert.ok(state.events <= 257);
});
