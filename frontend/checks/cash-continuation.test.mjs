import test from "node:test";
import assert from "node:assert/strict";
import { cashContinuation } from "../src/features/bankDemo/cashContinuation.js";

test("a cash estimate cannot be offered as an exact input", () => {
  for (const phrase of ["more than", "above", "at most", "approximately"]) {
    const result = cashContinuation(`For this day compare ${phrase} USD 412 in available funds with USD 526 in projected payments.`);
    assert.equal(result?.amounts, undefined);
    assert.match(result.hint, /exact/);
  }
});

test("a worksheet must include all material conditions in its two final figures", () => {
  const plain = "For this quarter, compare USD 510 in available cash with USD 429 in projected outflows.";
  assert.equal(cashContinuation(plain).amounts.length, 2);
  for (const clause of ["after retaining a third of the cash", "with a separate vendor credit still pending",
    "once the pledge is released", "before we have accounted for the extra insurance"]) {
    const value = cashContinuation(plain + " " + clause);
    assert.equal(value.amounts, undefined);
    assert.match(value.hint, /final available cash/);
  }
});

test("a cash worksheet keeps the exact source and the two amounts unassigned", () => {
  const question = "Our monthly cash is USD 4,097.32 and projected outflows are USD 3,295.08. How much covers them?";
  assert.deepEqual(cashContinuation(question), {
    question, period: "month",
    amounts: [{literal: "4,097.32", value: "4097.32"}, {literal: "3,295.08", value: "3295.08"}],
  });
  assert.deepEqual(cashContinuation("Today cash is USD 39.12 and outflows are USD 39.12.")?.amounts.map(a => a.value), ["39.12", "39.12"]);
  assert.equal(cashContinuation("Quarterly USD worksheet: available cash 130 and outflows 34.")?.period, "quarter");
});

test("a shared USD label cannot override the currency quoted next to an amount", () => {
  for (const quote of ["cad 750", "750 cad", "EuR 750", "750 in eur", "cHf750", "750chf", "bob 750", "750 BOB"]) {
    const result = cashContinuation(`On our monthly USD worksheet, available cash is USD 540 and projected outflows are ${quote}.`);
    assert.match(result?.hint ?? "", /verified USD/, quote);
    assert.equal(result?.amounts, undefined, quote);
  }
  const prose = "Bob reviewed all figures on our monthly USD worksheet. Available cash is USD 540 and outflows are 750 usd.";
  assert.deepEqual(cashContinuation(prose)?.amounts.map(amount => amount.value), ["540", "750"]);
});

test("mismatched windows, missing or signed figures and currencies cannot open a quoted calculation", () => {
  for (const question of [
    "Tomorrow USD 57.36 in cash is available; outgoing cash this month is USD 49.35.",
    "Cash in May is USD 300 and outflows in July are USD 296.",
    "Today's available cash was USD 543.81. Last Tuesday's outflows were USD 30.89.",
    "May we cover cash outflows of USD 62 with USD 75?",
    "Today's cash is $11; outflows are awaiting the forecast.",
    "Cash today is CAD 96.40 and outflows are USD 61.",
    "Today cash is USD -98 and outflows are USD 60.",
    "Cash today is -USD 31.78 and outflows USD 11.88.",
    "Will our daily cash of USD 50 cover outflows of NOK 40?",
    "Can cash of USD 40 today cover 28 in yen of outflows?",
    "Our cash is USD 81, and the daily outflows are 75 in another unit.",
    "Daily available cash is USD 79 and expected outflows are ₹45.",
    "Our overdrawn cash balance today is $63.27; expected outflows are $40.",
    "Cash is $31.78- today and expected outflows are $11.88.",
    "Today's cash is $.71 and outflows are $1.30.",
    "Today's cash is $2.5 million and outflows are $2.3 million.",
  ]) assert.equal(cashContinuation(question)?.amounts, undefined, question);
  assert.equal(cashContinuation("Show the report of cash and projected outflows for the month"), null);
  assert.equal(cashContinuation("Chart the count of transactions by account"), null);
  assert.equal(cashContinuation("Please wire USD 49 from available cash today to cover outflows of USD 35."), null);
  assert.equal(cashContinuation("Compare the USD 26.71 cash outflows today against previous cash outflows of USD 25.28."), null);
});
