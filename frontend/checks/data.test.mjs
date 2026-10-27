import test from "node:test";
import assert from "node:assert/strict";
import { createCsv, createTsv, safeCsvCell, safeTsvCell, formatCell, formatMetric } from "../src/components/data/financialValues.js";

test("clipboard TSV treats text and headers as literals while keeping negative numbers numeric", () => {
  const table = {
    columns: [{ key: "label", label: "=HYPERLINK(\"https://attacker.invalid\")" }, { key: "amount", label: "Amount" }],
    rows: [{ label: "=1+1", amount: -42.5 }, { label: "@SUM(1)", amount: 1500 }]
  };
  assert.equal(createTsv(table), '\"\'=HYPERLINK(\"\"https://attacker.invalid\"\")\"\tAmount\n\'=1+1\t-42.5\n\'@SUM(1)\t1500');
});

test("clipboard cell controls cannot manufacture new rows or columns", () => {
  const table = {
    columns: [{ key: "label", label: "Safe\t=1+1\n@SUM(1)" }],
    rows: [{ label: "ordinary\t=1+1\r\n@SUM(1)" }, { label: "\u0000=1+1" }]
  };
  const text = createTsv(table);
  assert.equal(text.split("\n").length, 3);
  assert.equal(text.includes("\t"), false);
  assert.equal(text.includes("\r"), false);
  assert.equal(text.includes("\u0000"), false);
  assert.equal(text.split("\n")[2], "' =1+1");
});

test("CSV and clipboard protect formula prefixes behind ignored control characters", () => {
  for (const prefix of ["", " ", "\t", "\n", "\u0000", "\u0001", "\u007f", "\u0085", "\u200b", "\u202e", "\u2066", "\ufeff"]) {
    for (const formula of ["=1+1", "+SUM(1)", "-42", "@SUM(1)"]) {
      assert.equal(safeCsvCell(prefix + formula).startsWith('"\''), true);
      assert.equal(safeTsvCell(prefix + formula).startsWith("'"), true);
    }
  }
  assert.equal(safeTsvCell(-42.5), "-42.5");
  assert.equal(safeTsvCell('"=1+1"'), '"""=1+1"""');
});

test("CSV preserves delimiters/newlines, protects formulas, and retains negative numbers", () => {
  assert.equal(safeCsvCell('line, "quote"\nnext'), '"line, ""quote""\nnext"');
  assert.equal(safeCsvCell("  =SUM(A1:A2)"), '"\'  =SUM(A1:A2)"');
  assert.equal(safeCsvCell("@SUM(1)"), '"\'@SUM(1)"');
  assert.equal(safeCsvCell(-42.5), '"-42.5"');
  assert.equal(safeCsvCell(null), '""');
  const csv = createCsv({ columns: [{ key: "amount", label: "Amount" }], rows: [{ amount: -9 }] });
  assert.equal(csv, '\uFEFF"Amount"\r\n"-9"');
});

test("financial formatting honors currency metadata and percentage points", () => {
  assert.equal(formatCell(25.5, { type: "currency", currency: "EUR", fractionDigits: 2 }), "€25.50");
  assert.equal(formatCell(48.2, { type: "percentage" }), "48.2%");
  assert.equal(formatCell(null, { type: "number" }), "—");
});

test("headline numbers use explicitly declared currencies", () => {
  assert.equal(formatMetric(1364203, "currency", "CZK"), "CZK\u00a01,364,203");
  assert.equal(formatMetric(1500, "currency", "USD"), "$1,500");
  assert.equal(formatMetric(12.5, "percentage"), "12.5%");
  assert.equal(formatMetric(1234.56, "number"), "1,234.6");
});

test("years and ids are shown without thousands separators", async () => {
  const { formatCell, formatMetric } = await import("../src/components/data/financialValues.js");
  assert.equal(formatCell(1993, { type: "string" }), "1993");
  assert.equal(formatCell(1139, { type: "number" }), "1,139");
  assert.equal(formatMetric(1993, "string"), "1993");
  assert.equal(formatMetric(1139, "number"), "1,139");
});
