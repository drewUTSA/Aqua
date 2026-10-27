import test from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";
import { displayTable } from "../src/components/data/displayTable.js";
import { workspaceResultMetadata } from "../src/services/workspaceResultMetadata.js";
import { createCsv, createTsv } from "../src/components/data/financialValues.js";
import { buildPlotlyFigure } from "../src/services/plotlyFigure.js";
import { plotlyFixture } from "./plotly-fixture.mjs";

// Compile the actual component with the existing locked build tool. No DOM,
// chart engine, network, provider or extra testing dependency is introduced.
const componentUrl = new URL("../src/components/data/FinancialTable.jsx", import.meta.url);
const transformed = await transformWithEsbuild(await readFile(componentUrl, "utf8"), componentUrl.pathname, { loader: "jsx", format: "esm" });
const code = transformed.code.replace(/from\s+["']([^"']+)["']/g, (_, specifier) =>
  `from ${JSON.stringify(specifier === "react" ? import.meta.resolve("react") : new URL(specifier, componentUrl).href)}`);
const { default: FinancialTable } = await import("data:text/javascript;base64," + Buffer.from(code).toString("base64"));
const render = (table) => renderToStaticMarkup(React.createElement(FinancialTable, { table }));
const fixture = () => ({ id: "result", title: "Owned result", columns: [{ key: "label", label: "Label", type: "string" }, { key: "amount", label: "Amount", type: "number" }],
  rows: [{ label: "Normal", amount: -12.5 }, { label: "Zero", amount: 0 }, { label: "Missing", amount: null }] });

test("actual table SSR retains valid negative, zero and missing values with accessible export/sort controls", () => {
  const table = fixture(), html = render(table);
  assert.equal(displayTable(table), table); assert.match(html, /<table>/); assert.match(html, />-12\.5</); assert.match(html, />0</);
  assert.match(html, /Sort by Amount/); assert.match(html, /Copy table/); assert.match(html, /Download CSV/);
  assert.match(html, /scope="col"/); assert.match(html, /role="region"/); assert.equal(html.includes("unavailable"), false);
});

const malformed = [
  ["null table", () => null], ["array table", () => []],
  ["object title", (table) => ({ ...table, title: { html: "PRIVATE" } })],
  ["object ID", (table) => ({ ...table, id: { path: "PRIVATE" } })],
  ["object column label", (table) => { table.columns[0].label = { html: "PRIVATE" }; return table; }],
  ["unknown column type", (table) => { table.columns[0].type = "html"; return table; }],
  ["invalid fraction digits", (table) => { table.columns[1].fractionDigits = 99; return table; }],
  ["noninteger fraction digits", (table) => { table.columns[1].fractionDigits = "2"; return table; }],
  ["invalid table currency", (table) => ({ ...table, currency: "PRIVATE_INVALID" })],
  ["object column currency", (table) => { table.columns[1].currency = { value: "PRIVATE" }; return table; }],
  ["object rows", (table) => ({ ...table, rows: { payload: "PRIVATE" } })],
  ["null row", (table) => { table.rows[0] = null; return table; }],
  ["nested object cell", (table) => { table.rows[0].label = { html: "PRIVATE" }; return table; }],
  ["nested array cell", (table) => { table.rows[0].label = ["PRIVATE"]; return table; }],
  ["nonfinite number", (table) => { table.rows[0].amount = Infinity; return table; }],
  ["duplicate binding", (table) => { table.columns[1].key = "label"; return table; }],
  ["missing cell", (table) => { delete table.rows[0].label; return table; }],
  ["extra executable metadata", (table) => ({ ...table, config: { html: "PRIVATE" } })]
];
for (const [name, change] of malformed) test(`malformed ${name} yields unavailable SSR without throwing or export controls`, () => {
  const table = change(fixture()); let html;
  assert.doesNotThrow(() => { html = render(table); }); assert.equal(displayTable(table), null);
  assert.match(html, /role="status"/); assert.match(html, /table is unavailable/);
  assert.equal(/<table|<button|PRIVATE|plotly/i.test(html), false);
});

test("display limits bound columns, rows and UTF-8 bytes without silently cropping", () => {
  const columns = fixture(); columns.columns = Array.from({ length: 65 }, (_, index) => ({ key: `c${index}`, label: "Column", type: "string" }));
  assert.equal(displayTable(columns), null);
  const rows = fixture(); rows.rows = Array.from({ length: 1001 }, () => ({ label: "Row", amount: 1 })); assert.equal(displayTable(rows), null);
  const bytes = fixture(); bytes.rows = Array.from({ length: 50 }, () => ({ label: "界".repeat(1700), amount: 1 }));
  assert.equal(displayTable(bytes), null); assert.match(render(bytes), /unavailable/); assert.equal(bytes.rows.length, 50);
  const boundary = fixture(); boundary.rows = Array.from({ length: 1000 }, () => ({ label: "Row", amount: 1 }));
  assert.equal(displayTable(boundary), boundary); assert.equal((render(boundary).match(/<td/g) || []).length, 2000);
});

test("a bounded long question title and received finite float remain available while geometry stays conservative", () => {
  const { descriptor, table } = plotlyFixture({ rows: [{ label: "Received float", amount: 9007199254740994 }] });
  table.title = "Q".repeat(2000);
  assert.equal(displayTable(table), table); assert.match(render(table), /9,007,199,254,740,994/);
  assert.ok(render(table).includes(table.title)); assert.ok(createCsv(table).includes('"9007199254740994"'));
  assert.equal(buildPlotlyFigure(descriptor, table), null);
  table.title = "Q".repeat(4001); assert.equal(displayTable(table), null);
});

test("owned reserved aliases and hostile literal text remain table data with safe export", () => {
  const table = { id: "result", title: '<img src="https://outside.invalid">', columns: ["constructor", "__proto__", "prototype"].map((key) => ({ key, label: key, type: "string" })),
    rows: [JSON.parse('{"constructor":"=PRIVATE()","__proto__":"<a href=https://outside.invalid>X</a>","prototype":"@PRIVATE()"}')] };
  assert.equal(displayTable(table), table); const html = render(table);
  assert.match(html, /&lt;img/); assert.match(html, /&lt;a href/); assert.equal(/<img|<a |<script/.test(html), false);
  assert.ok(createCsv(table).includes("'=PRIVATE()")); assert.ok(createTsv(table).includes("'@PRIVATE()"));
});

test("exact cells retain original identity, full strings and narrow CSV provenance", () => {
  const response = { status: "success", tables: [fixture()], kpis: [], visualizations: [] };
  response.tables[0].rows = [{ label: "Exact", amount: 9007199254740992 }];
  const metadata = { version: 1, source: { id: "a".repeat(64), freshness_at: null }, generated_at: "2026-10-27T00:00:00Z", filters: null,
    truncated: false, max_rows: 1000, aggregation: "unknown", column_units: { label: null, amount: null },
    exact_values: [{ row: 0, column: "amount", value: "9007199254740993", kind: "integer" }] };
  const table = workspaceResultMetadata(response, metadata).tables[0], row = table.rows[0];
  assert.equal(displayTable(table), table); assert.equal(table.rows[0], row); assert.match(render(table), /9007199254740993/);
  assert.ok(createCsv(table).includes('"9007199254740993"')); assert.ok(createTsv(table).includes("9007199254740993"));
});

test("inherited fields, getters and sparse arrays cannot execute inside display validation", () => {
  let calls = 0; const accessor = fixture(); Object.defineProperty(accessor, "title", { get: () => { calls++; throw Error("PRIVATE"); }, enumerable: true });
  assert.equal(displayTable(accessor), null); assert.match(render(accessor), /unavailable/); assert.equal(calls, 0);
  const inherited = fixture(); Object.setPrototypeOf(inherited, { title: "PRIVATE" }); assert.equal(displayTable(inherited), null);
  const sparse = fixture(); delete sparse.rows[0]; assert.equal(displayTable(sparse), null);
});
