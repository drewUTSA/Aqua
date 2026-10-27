import assert from "node:assert/strict";
import test from "node:test";
import { workspaceResultMetadata } from "../src/services/workspaceResultMetadata.js";
import { createCsv, createTsv, formatCell, sortTableRows } from "../src/components/data/financialValues.js";
import { compareExactNumeric } from "../src/services/precisionCells.js";
import { messageRecord } from "../src/services/workspaceContract.js";
import { snapshot } from "./analysis-fixture.mjs";

const response = () => ({ status: "success", message: "Owned result", tables: [{ id: "result", title: "Query results", columns: [{ key: "amount", label: "Amount", type: "number" }], rows: [
  { amount: 9007199254740992 }, { amount: -0.12345678901234568 }] }], visualizations: [{ id: "rounded-chart" }], kpis: [{ value: 9007199254740992 }] });
const metadata = () => ({ version: 1, source: { id: "a".repeat(64), freshness_at: null }, generated_at: "2026-10-26T12:00:00Z", filters: null,
  truncated: false, max_rows: 1000, aggregation: "unknown", column_units: { amount: null }, exact_values: [
    { row: 0, column: "amount", value: "9007199254740993", kind: "integer" }, { row: 1, column: "amount", value: "-0.1234567890123456789", kind: "decimal" }] });

test("workspace exact cells preserve big integers/decimals in display and sorted CSV/clipboard", () => {
  const normalized = workspaceResultMetadata(response(), metadata()), table = normalized.tables[0];
  assert.equal(formatCell(table.rows[0].amount, table.columns[0]), "9007199254740993");
  assert.equal(formatCell(table.rows[1].amount, table.columns[0]), "-0.1234567890123456789");
  const csv = createCsv(table, [...table.rows].reverse()), tsv = createTsv(table, [...table.rows].reverse());
  assert.ok(csv.includes('"-0.1234567890123456789"')); assert.equal(csv.includes("'-0.123"), false);
  assert.ok(tsv.includes("-0.1234567890123456789")); assert.equal(tsv.includes("'-0.123"), false);
  assert.deepEqual(normalized.visualizations, []); assert.deepEqual(normalized.kpis, []); assert.match(normalized.precisionNote, /avoid rounding/);
  assert.equal(response().tables[0].rows[0].amount, 9007199254740992);
});

test("precision provenance never grants unrelated or cloned table rows a spreadsheet escaping bypass", () => {
  const table = workspaceResultMetadata(response(), metadata()).tables[0];
  const clone = structuredClone(table); assert.ok(createCsv(clone).includes("'-0.1234567890123456789"));
  const foreign = { ...table, rows: [{ amount: "-1+PRIVATE_FORMULA()" }] }; assert.ok(createCsv(foreign).includes("'-1+PRIVATE_FORMULA()"));
});

test("ordinary decimals and older P06 results remain unchanged without exact overrides", () => {
  const old = response(); assert.equal(workspaceResultMetadata(old, undefined), old);
  const ordinary = metadata(); ordinary.exact_values = [];
  const normalized = workspaceResultMetadata(old, ordinary); assert.deepEqual(normalized.kpis, old.kpis); assert.deepEqual(normalized.visualizations, old.visualizations);
  assert.equal(normalized.tables[0].rows[0].amount, old.tables[0].rows[0].amount); assert.equal(normalized.precisionNote, undefined);
});

test("closed metadata rejects duplicated, foreign, mismatched or executable cell replacements", () => {
  const changes = [
    (value) => value.exact_values.push(value.exact_values[0]), (value) => { value.exact_values[0].column = "foreign"; },
    (value) => { value.exact_values[0].row = 1000; }, (value) => { value.exact_values[0].value = "1"; },
    (value) => { value.exact_values[0].value = "=PRIVATE_FORMULA()"; }, (value) => { value.exact_values[0].value = "-1+2"; },
    (value) => { value.exact_values[0].value = "9".repeat(257); }, (value) => { value.exact_values[0].kind = "float"; },
    (value) => { value.foreign = "PRIVATE"; }, (value) => { value.source.url = "https://foreign.invalid"; },
    (value) => { value.column_units.amount = "invented unit"; }, (value) => { value.column_units.foreign = null; }
  ];
  for (const change of changes) { const value = metadata(); change(value); assert.throws(() => workspaceResultMetadata(response(), value), /workspace_invalid_response/); }
  const foreign = response(); foreign.tables[0].id = "foreign-table"; assert.throws(() => workspaceResultMetadata(foreign, metadata()));
  const second = response(); second.tables.push({ ...second.tables[0], id: "unrelated" }); assert.throws(() => workspaceResultMetadata(second, metadata()));
});

test("row, column, metadata size and exact-value counts have explicit bounds", () => {
  const cases = [
    () => { const value = response(); value.tables[0].rows = Array(1001).fill({ amount: 1 }); return [value, metadata()]; },
    () => { const value = response(); value.tables[0].columns = Array.from({ length: 65 }, (_, index) => ({ key: `c${index}` })); return [value, metadata()]; },
    () => { const value = metadata(); value.exact_values = Array(1025).fill(value.exact_values[0]); return [response(), value]; },
    () => { const value = metadata(); value.exact_values = Array(1024).fill({ row: 0, column: "amount", value: "9".repeat(256), kind: "decimal" }); return [response(), value]; }
  ];
  for (const make of cases) assert.throws(() => workspaceResultMetadata(...make()), /workspace_invalid_response/);
});

test("metadata is workspace-only and revoked historical results never normalize or retain precision payloads", () => {
  const message = snapshot("complete", "complete").assistant_message;
  message.response = { ...response(), sql: "SELECT 1", result_metadata: metadata() };
  assert.equal(messageRecord(message).response.tables[0].rows[0].amount, "9007199254740993");
  message.result_unavailable = true; message.response.result_metadata = { private: "PRIVATE_SECRET" };
  assert.equal(JSON.stringify(messageRecord(message)).includes("PRIVATE_SECRET"), false); assert.deepEqual(messageRecord(message).response.tables, []);
});

test("exact table sorting compares negative decimals and close unsafe integers without Number rounding", () => {
  const values = ["-0.1234567890123456789", "-0.1234567890123456790", "9007199254740993", "9007199254740992", "0.1"];
  const raw = response(); raw.tables[0].rows = values.map((value) => ({ amount: Number(value) }));
  const sidecar = metadata(); sidecar.exact_values = values.map((value, row) => ({ row, column: "amount", value, kind: value.includes(".") ? "decimal" : "integer" }));
  const table = workspaceResultMetadata(raw, sidecar).tables[0], ascending = sortTableRows(table, { key: "amount", direction: "asc" });
  assert.deepEqual(ascending.map((row) => row.amount), [values[1], values[0], values[4], values[3], values[2]]);
  assert.deepEqual(sortTableRows(table, { key: "amount", direction: "desc" }), [...ascending].reverse());
  assert.ok(createCsv(table, ascending).includes('"-0.1234567890123456790"')); assert.equal(createCsv(table, ascending).includes("'-0.123"), false);
  for (const [left, right, expected] of [["0.1000000000000000001", 0.1, 1], ["1.0000000000000000001", 1, 1], ["0.00000001", 1e-8, 0], ["999999999999999999999", 1e21, -1], ["-0.0", 0, 0], ["-1.0", -1, 0]]) {
    assert.equal(compareExactNumeric(left, right), expected);
  }
});
