import assert from "node:assert/strict";
import test from "node:test";
import { MAX_RUNTIME_RECORDS, RuntimeDiagnostics, resolveFailure } from "./runtime-diagnostics.mjs";

const origin = "http://127.0.0.1:40123";
const asset = { name: "/assets/PlotlyChart-fixed.js", sha256: "a".repeat(64) };
const canary = "SYNTHETIC_PRIVATE_CANARY_9541@example.invalid";
const diagnostics = () => new RuntimeDiagnostics({ origin, assets: [asset], canarySha256: "b".repeat(64) });
function thrown(id = 41, changes = {}) {
  return { exceptionDetails: {
    exceptionId: id, text: "Uncaught " + canary,
    exception: { className: "TypeError", description: canary, objectId: canary, value: canary },
    stackTrace: { callFrames: [{ functionName: canary, scriptId: canary, url: origin + asset.name, lineNumber: 7, columnNumber: 19 }] },
    executionContextId: 91234, scriptId: canary, ...changes,
  } };
}

test("only whitelisted metadata and approved source hashes survive a thrown event", () => {
  const state = diagnostics(); state.observeThrown(thrown(), "visual");
  assert.deepEqual(state.snapshot(), {
    thrownCount: 1, revokedCount: 0, matchedRevokedCount: 0, invalid: false, overflow: false,
    records: [{ exceptionClass: "TypeError", sourceKind: "approved_asset", assetSha256: asset.sha256, line: 7, column: 19, phase: "visual", revoked: false }],
  });
  const raw = JSON.stringify(state.snapshot());
  assert.equal(raw.includes(canary), false);
  for (const forbidden of ["description", "objectId", "scriptId", "executionContextId", "exceptionId", "functionName", "stackTrace", "http:"]) assert.equal(raw.includes(forbidden), false);
  assert.equal(JSON.stringify(state), "{}");
});

test("secret URLs and unknown class or phase strings become fixed source categories", () => {
  for (const [url, expected] of [
    [origin + asset.name + "?token=" + canary, "same_origin_unknown"],
    [origin + "/verify-email#token=" + canary, "same_origin_document"],
    ["https://" + canary + "/private?proof=" + canary, "external_or_opaque"],
    ["data:text/plain," + canary, "external_or_opaque"],
    [canary, "unknown"],
  ]) {
    const state = diagnostics(); state.observeThrown(thrown(4, { exception: { className: canary }, stackTrace: { callFrames: [{ url, lineNumber: -1, columnNumber: 1000001, functionName: canary }] } }), canary);
    const value = state.snapshot(), record = value.records[0];
    assert.equal(record.sourceKind, expected); assert.equal(record.assetSha256, null);
    assert.equal(record.exceptionClass, "unknown"); assert.equal(record.phase, "unknown");
    assert.equal(record.line, null); assert.equal(record.column, null);
    assert.equal(JSON.stringify(value).includes(canary), false);
  }
});

test("canary script and document locations never expose their URL", () => {
  const state = diagnostics(); state.observeThrown(thrown(7, { stackTrace: { callFrames: [{ url: origin + "/__aqua-fixture/csp-probes.js", lineNumber: 0, columnNumber: 2 }] } }), "csp_canary");
  assert.deepEqual(state.snapshot().records[0], { exceptionClass: "TypeError", sourceKind: "canary_script", assetSha256: "b".repeat(64), line: 0, column: 2, phase: "csp_canary", revoked: false });
});

test("revocation correlates privately and never suppresses the runtime failure", () => {
  const state = diagnostics(); state.observeThrown(thrown(123456789), "visual");
  state.observeRevoked({ exceptionId: 123456789, reason: canary });
  state.observeRevoked({ exceptionId: 123456789, reason: canary });
  const value = state.snapshot();
  assert.equal(value.thrownCount, 1); assert.equal(value.revokedCount, 2); assert.equal(value.matchedRevokedCount, 1);
  assert.equal(value.records[0].revoked, true);
  assert.ok(value.thrownCount > 0); // Existing fail-on-any boundary remains red.
  assert.equal(JSON.stringify(value).includes("123456789"), false);
  assert.equal(JSON.stringify(value).includes(canary), false);
  value.records[0].revoked = false;
  assert.equal(state.snapshot().records[0].revoked, true);
});

test("overflow and malformed values have finite output without invoking getters", () => {
  const state = diagnostics();
  for (let index = 0; index < 100; index++) state.observeThrown(thrown(index), "visual");
  state.observeRevoked({ exceptionId: canary, reason: canary });
  const value = state.snapshot();
  assert.equal(value.records.length, MAX_RUNTIME_RECORDS); assert.equal(value.thrownCount, 100);
  assert.equal(value.overflow, true); assert.equal(value.invalid, true);
  assert.ok(JSON.stringify(value).length < 3000); assert.equal(JSON.stringify(value).includes(canary), false);
  const malformed = diagnostics();
  malformed.observeThrown(Object.defineProperty({}, "exceptionDetails", { get() { throw Error(canary); } }), "visual");
  assert.equal(malformed.snapshot().invalid, true);
  assert.equal(malformed.snapshot().thrownCount, 1);
  assert.equal(malformed.snapshot().records[0].exceptionClass, "unknown");
  assert.equal(JSON.stringify(malformed.snapshot()).includes(canary), false);
});

test("configuration rejects duplicate or unapproved asset references", () => {
  for (const options of [
    { origin: "javascript:" + canary }, { origin, assets: [asset, asset] },
    { origin, assets: [{ name: "/../secret", sha256: asset.sha256 }] },
    { origin, assets: [{ name: "/assets/chart.js", sha256: canary }] },
    { origin, canarySha256: canary },
  ]) assert.throws(() => new RuntimeDiagnostics(options), /^Error: runtime_diagnostic_configuration_invalid$/);
});

test("actual boundary category stays separate from the last successful stage and only fixed phases survive", () => {
  const stage = "document CSP blocks actual inline scripts handlers evaluation and base changes";
  for (const phase of ["setup", "authentication", "visual", "csp_canary", "final_boundary", "cleanup", "unknown"])
    assert.deepEqual(resolveFailure(Error("browser_boundary_failure"), phase), { failure_category: "browser_boundary_failure", failure_stage: phase });
  assert.deepEqual(resolveFailure(Error("browser_boundary_failure"), stage), { failure_category: "browser_boundary_failure", failure_stage: "unknown" });
  for (const error of [Error(canary), { message: canary }, Object.defineProperty({}, "message", { get() { throw Error(canary); } })]) {
    const value = resolveFailure(error, canary);
    assert.deepEqual(value, { failure_category: "browser_fixture_failed", failure_stage: "unknown" });
    assert.equal(JSON.stringify(value).includes(canary), false);
  }
});
