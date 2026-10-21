import assert from "node:assert/strict";
import test from "node:test";
import { consumeLocation, navigateLocal } from "../src/services/routes.js";

test("email proofs are captured privately and removed before UI or SDK setup", () => {
  for (const path of ["/verify-email", "/reset-password"]) {
    const calls = [];
    const proof = "A".repeat(43);
    const route = consumeLocation({ pathname: path, search: "?return=https://attacker.invalid", hash: "#token=" + proof }, { replaceState: (...args) => calls.push(args) });
    assert.deepEqual(route, { path, proof });
    assert.deepEqual(calls, [[null, "", path]]);
    assert.ok(!JSON.stringify(calls).includes(proof));
  }
});
test("malformed, duplicate, misplaced and active fragments cannot become a proof or redirect", () => {
  for (const hash of ["#token=short", "#token=" + "A".repeat(43) + "&token=other", "#token=%3Cscript%3E", "#javascript:alert(1)", "#token=" + "A".repeat(5000)]) {
    const calls = [];
    const route = consumeLocation({ pathname: "/reset-password", search: "", hash }, { replaceState: (...args) => calls.push(args) });
    assert.equal(route.proof, null);
    assert.deepEqual(calls, [[null, "", "/reset-password"]]);
  }
  assert.equal(consumeLocation({ pathname: "/signin", hash: "#token=" + "A".repeat(43) }, { replaceState() {} }).proof, null);
});
test("navigation cannot send credentials or session state to arbitrary destinations", () => {
  const calls = [];
  const history = { pushState: (...args) => calls.push(args) };
  const updates = [];
  for (const path of ["https://attacker.invalid", "//attacker.invalid", "javascript:alert(1)", "/signin?token=secret", "/reset-password#token=secret", "/api/query", "/../settings"]) {
    assert.equal(navigateLocal(path, history, (value) => updates.push(value)), false);
  }
  assert.equal(calls.length, 0);
  assert.equal(updates.length, 0);
  assert.equal(navigateLocal("/settings", history, (value) => updates.push(value)), true);
  assert.deepEqual(updates, [{ path: "/settings", proof: null }]);
});
test("network-path-like unknown URLs are safely cleared into the local 404", () => {
  for (const pathname of ["//attacker.invalid", "/\\attacker.invalid", "\\attacker.invalid"]) {
    const calls = [];
    assert.deepEqual(consumeLocation({ pathname, search: "?secret=canary", hash: "#token=" + "A".repeat(43) }, { replaceState: (...args) => calls.push(args) }), { path: "/not-found", proof: null });
    assert.deepEqual(calls, [[null, "", "/not-found"]]);
  }
});
