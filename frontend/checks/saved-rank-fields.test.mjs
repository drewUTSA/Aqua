import assert from "node:assert/strict";
import test from "node:test";
import { rankGroupsDraft } from "../src/components/workspace/rankGroupsDraft.js";
import { savedRankFields } from "../src/components/workspace/savedRankFields.js";

const sql = "SELECT counter_id, COUNT(*) AS visits FROM public.turnstiles GROUP BY counter_id ORDER BY visits DESC LIMIT 2";
const question = "Which are the top two counters by visit count?";
const expected = { source: "turnstiles", group: "counter_id", measure: "count", field: "", direction: "top", number: "2", ties: "" };

test("a requested and executed grouped count identifies the physical fields and waits for a tie policy", () => {
  for (const order of ["visits", "COUNT(*)", "2"]) {
    const fields = savedRankFields(sql.replace("BY visits", "BY " + order), question);
    assert.deepEqual(fields, expected);
    assert.equal(rankGroupsDraft(fields), "");
    assert.equal(rankGroupsDraft({ ...fields, ties: "peers" }), "Rank groups: From turnstiles, show the top 2 counter_id by row count, including ties.");
  }
});

test("a quoted and aliased grouped total keeps physical names and treats FETCH WITH TIES as a rule to review", () => {
  const totalSql = 'SELECT r."sensor_id" AS room, SUM(r."volume_l") AS amount FROM "public"."samples" AS r GROUP BY 1 ORDER BY amount FETCH NEXT 4 ROWS WITH TIES;';
  const fields = savedRankFields(totalSql, "List the 4 smallest totals by sensor.");
  assert.deepEqual(fields, { source: "samples", group: "sensor_id", measure: "total", field: "volume_l", direction: "bottom", number: "4", ties: "" });
  assert.equal(rankGroupsDraft({ ...fields, ties: "levels" }), "Rank groups: From samples, which sensor_id have one of the lowest 4 distinct total volume_l values?");
  assert.deepEqual(savedRankFields(totalSql.replace("BY 1", 'BY r."sensor_id"').replace("BY amount", 'BY SUM(r."volume_l") ASC'), "Show the bottom four sensors."), fields);
  assert.deepEqual(savedRankFields(sql.toUpperCase(), "Show the highest two counters."), expected);
});

test("the full saved query must preserve the source population, grouping and score", () => {
  const changes = [
    ["public.", "audit."], ["turnstiles", '"Turnstiles"'], ["counter_id,", '"counter id",'], ["counter_id,", 'x.counter_id,'],
    ["counter_id,", 'counter__id,'], ["visits FROM", "counter_id FROM"], ["GROUP BY", "JOIN visits v ON v.id = counter_id GROUP BY"],
    ["GROUP BY", "WHERE active GROUP BY"], ["BY counter_id ORDER", "BY counter_id, day ORDER"],
    ["ORDER BY", "HAVING COUNT(*) > 1 ORDER BY"], ["BY visits DESC", "BY counter_id DESC"], ["DESC LIMIT", "DESC, counter_id LIMIT"],
    ["COUNT(*)", "COUNT(user_id)"], ["COUNT(*)", "COUNT(DISTINCT user_id)"], ["COUNT(*)", "SUM(x.fee)"],
    ["COUNT(*)", "SUM(counter_id)"], ["COUNT(*)", "AVG(fee)"], ["DESC LIMIT", "DESC NULLS LAST LIMIT"],
    ["LIMIT 2", "LIMIT 2 OFFSET 1"], ["LIMIT 2", ""], ["SELECT", "SELECT DISTINCT"], ["SELECT", "WITH src AS (SELECT 1) SELECT"],
    ["LIMIT 2", "LIMIT 2; SELECT 1"], ["BY counter_id ORDER", "BY something_else ORDER"],
  ];
  for (const [before, after] of changes) {
    const variant = sql.replace(before, after);
    assert.equal(savedRankFields(variant, question), null, variant);
  }
});

test("a row cap or incidental, contradictory or imprecise number never preselects the employee cutoff", () => {
  const unconfirmed = ["Show the busiest counters.", "For the last two months, rank counters.", "The bottom two counters.",
    "Compare the top 2 and the bottom 2 counters.", "Compare the top 2 and top 3 counters.", "Show the top 3 counters.",
    "The top 2% of counters.", "The top two percent of counters.", "The top 2.5 counters.", "The top 2,500 counters.",
    "The top two hundred counters.", "The twenty two highest visit counts.", "The 1.2 highest totals.", "Compare the top 2–4.",
    "The top two or three counters.", "Show the top two and a half counters.", null, "x".repeat(2001)];
  for (const text of unconfirmed) assert.equal(savedRankFields(sql, text), null, String(text));
  assert.equal(savedRankFields(sql.replace("LIMIT 2", "LIMIT 1000"), "Top 1000 counters"), null);
  assert.equal(savedRankFields(null, question), null);
  assert.equal(savedRankFields(" ".repeat(4096) + sql, question), null);
});
