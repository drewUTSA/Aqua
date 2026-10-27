import test from "node:test";
import assert from "node:assert/strict";
import { createCsv, createTsv, formatCell, formatMetric } from "../src/components/data/financialValues.js";

test("unknown monetary units stay plain numbers without inventing USD", () => {
  assert.equal(formatCell(1500.25, { type: "currency" }), "1,500.25");
  assert.equal(formatCell(-25.5, { type: "currency", currency: "" }), "-25.5");
  assert.equal(formatMetric(1500, "currency"), "1,500");
  assert.equal(formatMetric(-25, "currency", null), "-25");
});

test("declared column/table currency keeps USD and CZK and column precedence", () => {
  assert.equal(formatCell(1500, { type: "currency", currency: "USD" }), "$1,500");
  assert.equal(formatCell(1500, { type: "currency" }, { currency: "CZK" }), "CZK\u00a01,500");
  assert.equal(formatCell(1500, { type: "currency", currency: "USD" }, { currency: "CZK" }), "$1,500");
  assert.equal(formatMetric(1500, "currency", "CZK"), "CZK\u00a01,500");
});

test("date-typed timestamps preserve full source time, offset and precision in table and TSV", () => {
  const values = ["2026-10-27T12:34:56.789+05:45", "2026-10-27T01:02:03.123456-07:00", "2026-10-27T00:00:00.000Z"];
  const table = { columns: [{ key: "occurred", label: "Occurred", type: "date" }], rows: values.map((occurred) => ({ occurred })) };
  for (const value of values) assert.equal(formatCell(value, table.columns[0], table), value);
  assert.equal(createTsv(table), `Occurred\n${values.join("\n")}`);
  assert.equal(createCsv(table), `\uFEFF"Occurred"\r\n${values.map((value) => `"${value}"`).join("\r\n")}`);
  assert.deepEqual(table.rows.map((row) => row.occurred), values);
});

test("valid standalone calendar days format without changing the date", () => {
  assert.equal(formatCell("2024-02-29", { type: "date" }), "Feb 29, 2024");
  assert.equal(formatCell("2026-10-27", { type: "date" }), "Oct 27, 2026");
  assert.equal(formatCell("2000-02-29", { type: "date" }), "Feb 29, 2000");
});

test("invalid calendar days and noncanonical dates remain literal instead of rolling forward", () => {
  const values = ["2026-02-30", "2025-02-29", "1900-02-29", "2026-13-01", "2026-04-31", "0000-01-01", "2026-2-3", "not a date"];
  for (const value of values) assert.equal(formatCell(value, { type: "date" }), value);
  assert.equal(createTsv({ columns: [{ key: "day", label: "Day", type: "date" }], rows: values.map((day) => ({ day })) }), `Day\n${values.join("\n")}`);
});

test("monetary table export keeps original negative numeric values and formula escaping", () => {
  const table = { columns: [{ key: "amount", label: "Amount", type: "currency", currency: "USD" }, { key: "day", label: "Day", type: "date" }],
    rows: [{ amount: -1500.25, day: "=PRIVATE_FORMULA()" }] };
  assert.equal(createTsv(table), "Amount\tDay\n-1500.25\t'=PRIVATE_FORMULA()");
  assert.equal(createCsv(table), '\uFEFF"Amount","Day"\r\n"-1500.25","\'=PRIVATE_FORMULA()"');
});
