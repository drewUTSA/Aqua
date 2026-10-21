import assert from "node:assert/strict";
import test from "node:test";
import { selectUiShell } from "../src/services/shellConfig.js";

test("shell rollback accepts only the exact deployment choice and defaults to Opal", () => {
  assert.equal(selectUiShell("legacy"), "legacy");
  for (const value of [undefined, null, "", "opal", false, true, 0, 1]) {
    assert.equal(selectUiShell(value), "opal");
  }
});

test("untrusted paths, markup and approximate shell names cannot select a presentation", () => {
  for (const value of ["Legacy", "LEGACY", " legacy", "legacy\n", "legacy?demo=true", "../legacy", "/legacy", "https://attacker.invalid/legacy", "<script>legacy</script>", "__proto__", "constructor"]) {
    assert.equal(selectUiShell(value), "opal");
  }
});

test("shell selection never coerces objects into executable configuration", () => {
  const value = { toString() { throw new Error("unexpected_coercion"); }, valueOf() { throw new Error("unexpected_coercion"); } };
  assert.equal(selectUiShell(value), "opal");
  assert.equal(selectUiShell(["legacy"]), "opal");
});
