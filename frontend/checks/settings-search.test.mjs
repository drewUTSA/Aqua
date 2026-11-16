import assert from "node:assert/strict";
import test from "node:test";
import { searchSettings } from "../src/settings/settingsSearch.js";
import { CATEGORIES } from "../src/settings/controls.js";

test("operational privacy and account labels are discoverable without being preference fields", () => {
  for (const query of ["import", "delete history", "download personal data"]) {
    const results = searchSettings(query);
    assert.deepEqual(results.map((category) => category.id), ["privacy"]);
    assert.deepEqual(results[0].fields, []);
  }
  assert.deepEqual(searchSettings("revoke session").map((category) => category.id), ["account"]);
  assert.deepEqual(searchSettings("change email").map((category) => category.id), ["account"]);
});

test("field search remains specific, bounded and leaves the source schema unchanged", () => {
  const before = structuredClone(CATEGORIES);
  const results = searchSettings(" TEXT size ");
  assert.deepEqual(results.map((category) => category.id), ["appearance", "accessibility"]);
  assert.ok(results.every((category) => category.fields.length === 1 && category.fields[0].key === "text_scale"));
  for (const value of [null, {}, "", "  ", "<script>PRIVATE()</script>", "x".repeat(10000)]) assert.deepEqual(searchSettings(value), []);
  assert.deepEqual(CATEGORIES, before);
  assert.ok(searchSettings("a").length <= CATEGORIES.length);
});
