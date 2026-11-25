import assert from "node:assert/strict";
import test from "node:test";
import { rankGroupsDraft } from "../src/components/workspace/rankGroupsDraft.js";
import { savedRankFields } from "../src/components/workspace/savedRankFields.js";

const hint = { source: "turnstiles", group: "counter_id", measure: "count", field: "", direction: "top", number: "2", ties: "" };
test("authorized non-executable hints preserve the review form and explicit choice of ties", () => {
  const fields = savedRankFields(hint);
  assert.deepEqual(fields, hint); assert.notEqual(fields, hint);
  assert.equal(rankGroupsDraft(fields), "");
  assert.equal(rankGroupsDraft({ ...fields, ties: "peers" }), "Rank groups: From turnstiles, show the top 2 counter_id by row count, including ties.");
  const total = { ...hint, measure: "total", field: "amount", direction: "bottom" };
  assert.deepEqual(savedRankFields(total), total);
});
test("raw statements, extra fields and unsafe or changed ranking hints cannot prefill the form", () => {
  for (const value of [null, [], "SELECT counter_id FROM turnstiles", {},
    { ...hint, sql: "SELECT private" }, { ...hint, source: "public.turnstiles" }, { ...hint, group: "counter__id" },
    { ...hint, source: "x".repeat(65) }, { ...hint, number: 2 }, { ...hint, number: "1000" }, { ...hint, number: "02" },
    { ...hint, ties: "fixed" }, { ...hint, measure: "avg" }, { ...hint, direction: "descending" },
    { ...hint, field: "amount" }, { ...hint, measure: "total" }, { ...hint, measure: "total", field: "counter_id" }]) {
    assert.equal(savedRankFields(value), null);
  }
});
