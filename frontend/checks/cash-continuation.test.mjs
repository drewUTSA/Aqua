import test from "node:test";
import assert from "node:assert/strict";
import { cashContinuation } from "../src/features/bankDemo/cashContinuation.js";

test("a cash worksheet keeps the exact source and the two amounts unassigned", () => {
  const question = "Our monthly cash is USD 4,097.32 and projected outflows are USD 3,295.08. How much covers them?";
  assert.deepEqual(cashContinuation(question), {
    question, period: "month",
    amounts: [{literal: "4,097.32", value: "4097.32"}, {literal: "3,295.08", value: "3295.08"}],
  });
  assert.deepEqual(cashContinuation("Today cash is USD 39.12 and outflows are USD 39.12.")?.amounts.map(a => a.value), ["39.12", "39.12"]);
});

test("mismatched windows, missing or signed figures and currencies cannot open a quoted calculation", () => {
  for (const question of [
    "Tomorrow USD 57.36 in cash is available; outgoing cash this month is USD 49.35.",
    "Cash in May is USD 300 and outflows in July are USD 296.",
    "May we cover cash outflows of USD 62 with USD 75?",
    "Today's cash is $11; outflows are awaiting the forecast.",
    "Cash today is CAD 96.40 and outflows are USD 61.",
    "Today cash is USD -98 and outflows are USD 60.",
    "Cash today is -USD 31.78 and outflows USD 11.88.",
    "Our overdrawn cash balance today is $63.27; expected outflows are $40.",
    "Cash is $31.78- today and expected outflows are $11.88.",
    "Today's cash is $.71 and outflows are $1.30.",
    "Today's cash is $2.5 million and outflows are $2.3 million.",
  ]) assert.equal(cashContinuation(question)?.amounts, undefined, question);
  assert.equal(cashContinuation("Show the report of cash and projected outflows for the month"), null);
  assert.equal(cashContinuation("Chart the count of transactions by account"), null);
  assert.equal(cashContinuation("Compare the USD 26.71 cash outflows today against previous cash outflows of USD 25.28."), null);
});
