import assert from "node:assert/strict";
import test from "node:test";
import { contextEnvelope, ownerId } from "./bank-demo-fixture.mjs";
import { decodeBankContext, decodeCalculation } from "../src/features/bankDemo/contract.js";
import { fieldsFromReport, operations, reportValues } from "../src/features/bankDemo/calculator.js";

const context = decodeBankContext(contextEnvelope(), ownerId);
const inputs = { principal_usd:"234.50", annual_rate_percent:"4", term_months:"12", currency:"USD" };
const draft = { operation:"simple_interest", expected_source_revision:context.sourceRevision, confirmedInputs:inputs };
const value = { schemaVersion:1, owner_id:ownerId, calculation:{ operation:draft.operation, currency:"USD", inputs,
  sourceRevision:context.sourceRevision, synthetic:true, executionEnabled:false, bankQuote:false, approvalRecorded:false,
  result:{interest_usd:"9.38",principal_plus_interest_usd:"243.88",term_months:"12"},
  explanation:"The interest is 9.38 USD.", assumptions:["Simple interest using twelve supplied months."],source:{kind:"employee_supplied"} } };

test("confirmed calculator preserves amounts, source, role owner and flags before rendering", () => {
  assert.equal(decodeCalculation(value, ownerId, context, draft).result.interest_usd, "9.38");
  for (const changes of [{inputs:{...inputs,principal_usd:"234.51"}}, {source:{kind:"institution_record"}},
    {bankQuote:true}, {operation:"liquidity_coverage"}, {result:{...value.calculation.result,interest_usd:"9.385"}},
    {result:{...value.calculation.result,term_months:"24"}}, {result:{...value.calculation.result,unrelated:"243.88"}}])
    assert.throws(() => decodeCalculation({...value,calculation:{...value.calculation,...changes}},ownerId,context,draft));
  assert.throws(() => decodeCalculation({...value,owner_id:"other"},ownerId,context,draft));
});

test("report selection maps only reviewed compatible fields and actual source cells", () => {
  const report={reportId:"commercial_exposure_summary",columns:[{key:"stage",unit:"text"},{key:"requested_usd",unit:"USD"},{key:"outstanding_usd",unit:"USD"}],
    rows:[["approved_not_funded","21700.00","0.00"]]};
  assert.equal(Object.keys(operations).length,6);
  assert.equal(fieldsFromReport("simple_interest",report).length,2);
  assert.deepEqual(fieldsFromReport("percent_change",report),[]);
  assert.deepEqual(reportValues(report,0,"outstanding_usd"),{principal_usd:"0.00"});
  assert.deepEqual(reportValues(report,0,"requested_usd"),{principal_usd:"21700.00"});
  assert.throws(()=>reportValues(report,0,"stage"));
  assert.throws(()=>reportValues(report,1,"requested_usd"));
});
