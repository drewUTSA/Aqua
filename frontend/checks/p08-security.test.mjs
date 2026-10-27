import assert from "node:assert/strict";
import test from "node:test";
import { validatePresentation, workspacePresentation } from "../src/services/presentationContract.js";
import { buildPlotlyFigure } from "../src/services/plotlyFigure.js";
import { createPlotlyController } from "../src/components/data/plotlyController.js";
import { initialWorkspace, finishSubmission } from "../src/hooks/workspaceState.js";
import { workspaceResultMetadata } from "../src/services/workspaceResultMetadata.js";
import { createCsv, createTsv } from "../src/components/data/financialValues.js";

const copy = (value) => structuredClone(value);
const turn = () => new Promise((resolve) => setImmediate(resolve));
test("P08 draft-to-canonical chat remapping keeps the visual owner identity", () => {
  const state = initialWorkspace(), draft = state.records[state.activeId], owner = draft.viewId;
  draft.operation = { clientId: "fixed-operation", prompt: "Show a chart" };
  const next = finishSubmission(state, draft.id, "fixed-operation", {
    chat: { id: "canonical-chat", revision: 1 }, request: { state: "queued", version: 1 },
    input: { id: "input", role: "user", sequence: 1 }, assistant: { id: "assistant", role: "aqua", sequence: 2 },
  });
  assert.equal(next.activeId, "canonical-chat");
  assert.equal(next.records["canonical-chat"].viewId, owner);
  assert.equal(next.records[draft.id], undefined);
});
function fixture(count = 2) {
  const table = { id: "result", title: "Owned result", columns: [{ key: "label", label: "Category", type: "string" }, { key: "amount", label: "Amount", type: "number" }],
    rows: Array.from({ length: count }, (_, index) => ({ label: `Category ${index}`, amount: index - 1 })) };
  const chart = { id: "result-chart", type: "bar", title: "Requested chart", tableId: "result", x: { keys: ["label"], kind: "category", timezone: null, calendar_parts: [] },
    series: [{ key: "amount", label: "Amount", unit: null }], row_indices: table.rows.map((_, index) => index), missing: "gap", reduction: "none",
    input_rows: count, output_points: count, downsampled: false, compatibility_key: "a".repeat(64), approximate: false };
  const presentation = { version: 1, intent: "explicit", default_view: "chart", reason: "requested_visual", charts: [chart] };
  const response = { status: "success", message: "Owned result", tables: [table], visualizations: [], kpis: [] };
  return { chart, table, presentation, response };
}
function denied(value) {
  assert.throws(() => validatePresentation(value.presentation, value.response), /presentation_invalid/);
  assert.equal(buildPlotlyFigure(value.chart, value.table), null);
  const safe = workspacePresentation(value.response, value.presentation);
  assert.equal(safe.tables, value.response.tables);
  assert.equal(safe.presentation, null);
  assert.match(safe.presentationError, /table/i);
}

const malformed = [
  ["raw engine config", (f) => { f.chart.config = { showSendToCloud: true }; }],
  ["remote layout image", (f) => { f.chart.layout = { images: [{ source: "https://outside.invalid/track" }] }; }],
  ["unsupported trace", (f) => { f.chart.type = "scattergl"; }],
  ["remote axis source", (f) => { f.chart.x.url = "https://outside.invalid/data"; }],
  ["model hover template", (f) => { f.chart.series[0].hovertemplate = "<img src=https://outside.invalid/track>"; }],
  ["duplicate rows", (f) => { f.chart.row_indices = [0, 0]; }],
  ["foreign table reference", (f) => { f.chart.tableId = "foreign-private-table"; }],
  ["unsafe numeric coordinate", (f) => { f.table.rows[0].amount = 9007199254740992; }],
  ["nonfinite coordinate", (f) => { f.table.rows[0].amount = Infinity; }],
  ["object cell", (f) => { f.table.rows[0].label = { src: "https://outside.invalid/track" }; }],
  ["unknown row field", (f) => { f.table.rows[0].extra = "private"; }],
  ["JSON prototype field", (f) => { Object.assign(f.chart, JSON.parse('{"constructor":{"prototype":{"p08polluted":true}}}')); }],
  ["JSON own __proto__ field", (f) => { Object.defineProperty(f.chart, "__proto__", { value: { p08polluted: true }, enumerable: true }); }],
  ["inherited configuration", (f) => { Object.setPrototypeOf(f.chart, { layout: { images: ["https://outside.invalid"] } }); }]
];
for (const [name, change] of malformed) test(`P08 rejects ${name} before a chart is usable`, () => {
  const value = fixture(); change(value); denied(value); assert.equal({}.p08polluted, undefined);
  const control = fixture(); assert.ok(buildPlotlyFigure(control.chart, control.table));
});

test("P08 hard point and UTF-8 byte limits never sample or alter the saved table", () => {
  const limit = fixture(50); assert.ok(buildPlotlyFigure(limit.chart, limit.table));
  denied(fixture(51));
  const tooMany = fixture(501); tooMany.chart.type = "line"; denied(tooMany);
  const bytes = fixture(50); bytes.table.columns.push({ key: "note", label: "Note", type: "string" });
  bytes.table.rows.forEach((row) => { row.note = "\u754c".repeat(1700); });
  assert.ok(new TextEncoder().encode(JSON.stringify(bytes.table)).byteLength > 240000);
  denied(bytes); assert.equal(bytes.table.rows.length, 50); assert.equal(bytes.table.rows[0].note.length, 1700);
});

test("P08 text remains literal and the engine has no cloud, links, math or embedded asset capability", () => {
  const value = fixture(), payload = '<a href="https://outside.invalid/track"><img src=x onerror=PRIVATE()></a>';
  value.chart.title = payload; value.chart.series[0].label = payload.slice(0, 80);
  value.table.rows[0].label = payload; value.table.columns[0].label = payload;
  const figure = buildPlotlyFigure(value.chart, value.table); assert.ok(figure);
  assert.match(figure.data[0].customdata[0][0], /&lt;a href=&quot;/);
  assert.equal(figure.data[0].customdata[0][0].includes("<img"), false);
  assert.equal(figure.data[0].name.includes("<a"), false); assert.equal(figure.layout.xaxis.title.text.includes("<a"), false);
  for (const key of ["showSendToCloud", "showLink", "sendData", "editable", "typesetMath", "displaylogo", "displayModeBar"]) assert.equal(figure.config[key], false, key);
  assert.deepEqual(figure.config.modeBarButtons, []); assert.equal(figure.config.plotlyServerURL, ""); assert.equal(figure.config.topojsonURL, "");
  assert.deepEqual(figure.data.map((trace) => trace.type), ["bar"]);
  assert.equal(value.table.rows[0].label, payload); // Escaping applies only to Plotly projection.
});

test("P08 whole-result exact values cannot be re-enabled by a forged descriptor and CSV remains safe", () => {
  const value = fixture(); value.table.columns.push({ key: "record_id", label: "Identifier", type: "string" });
  value.table.rows[0].record_id = 9007199254740992; value.table.rows[1].record_id = 7;
  value.table.rows[0].label = " \t=PRIVATE()";
  const metadata = { version: 1, source: { id: "b".repeat(64), freshness_at: null }, generated_at: "2026-10-27T00:00:00Z", filters: null,
    truncated: false, max_rows: 1000, aggregation: "unknown", column_units: { label: null, amount: null, record_id: null },
    exact_values: [{ row: 0, column: "record_id", value: "9007199254740993", kind: "integer" }] };
  value.response = workspaceResultMetadata(value.response, metadata); value.table = value.response.tables[0];
  denied(value); const csv = createCsv(value.table), tsv = createTsv(value.table);
  assert.ok(csv.includes("9007199254740993")); assert.ok(csv.includes("' \t=PRIVATE()")); assert.ok(tsv.includes("'  =PRIVATE()"));
  assert.ok(csv.includes('"-1"')); assert.equal(csv.includes("'-1"), false); assert.equal(value.table.rows[0].label, " \t=PRIVATE()");
});

test("P08 distinct compound categories never merge through their joined display labels", () => {
  const value = fixture(); value.table.columns.splice(1, 0, { key: "second", label: "Second", type: "string" });
  value.table.rows = [{ label: "a b", second: "c", amount: 2 }, { label: "a", second: "b c", amount: 3 }]; value.chart.x.keys.push("second");
  const figure = buildPlotlyFigure(value.chart, value.table); assert.ok(figure);
  assert.equal(new Set(figure.data[0].x).size, 2); assert.deepEqual(figure.data[0].y, [2, 3]);
  value.table.rows[1] = { ...value.table.rows[0], amount: 3 }; denied(value);
});

test("P08 two compatible series preserve their values and ambiguous units refuse the chart", () => {
  const value = fixture(); value.table.columns.push({ key: "other", label: "Other", type: "number" });
  value.table.rows.forEach((row, index) => { row.other = 5 + index; });
  value.chart.series[0].unit = "count"; value.chart.series.push({ key: "other", label: "Other", unit: "count" }); value.chart.output_points = 4;
  assert.doesNotThrow(() => validatePresentation(value.presentation, value.response));
  const figure = buildPlotlyFigure(value.chart, value.table); assert.deepEqual(figure.data.map((trace) => trace.y), [[-1, 0], [5, 6]]);
  for (const unit of [null, "USD"]) { const bad = copy(value); bad.chart.series[1].unit = unit; denied(bad); }
});

test("P08 genuine backend currency columns keep bounded fraction digits and declared units", () => {
  const value = fixture(); Object.assign(value.table.columns[1], { type: "currency", currency: "CZK", fractionDigits: 2 }); value.chart.series[0].unit = "CZK";
  assert.ok(buildPlotlyFigure(value.chart, value.table));
  assert.doesNotThrow(() => validatePresentation(value.presentation, value.response));
  const before = copy(value.table), figure = buildPlotlyFigure(value.chart, value.table);
  assert.equal(figure.layout.yaxis.title.text, "CZK"); assert.deepEqual(value.table, before);
});

test("P08 Python offset timestamps normalize only projected coordinates to UTC", () => {
  const value = fixture(); value.chart.type = "line"; value.chart.x = { keys: ["label"], kind: "datetime", timezone: "UTC", calendar_parts: [] };
  value.table.columns[0].type = "date"; value.table.rows[0].label = "2026-01-01T00:00:00+00:00"; value.table.rows[1].label = "2025-12-31T20:00:00-05:00";
  assert.doesNotThrow(() => validatePresentation(value.presentation, value.response));
  const figure = buildPlotlyFigure(value.chart, value.table); assert.ok(figure);
  assert.deepEqual(figure.data[0].x, ["2026-01-01T00:00:00.000Z", "2026-01-01T01:00:00.000Z"]);
  assert.equal(value.table.rows[1].label, "2025-12-31T20:00:00-05:00");
  for (const invalid of ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00.000001Z", "2026-02-30T01:00:00Z", "2026-01-01T01:00:00", "2026-01-01T01:00:00+25:00"]) {
    const bad = copy(value); bad.table.rows[1].label = invalid; bad.response.tables = [bad.table]; denied(bad);
  }
});

function controller(loadEngine) {
  const frames = new Map(), statuses = []; let next = 0, stopped = 0;
  const owner = createPlotlyController({ node: { isConnected: true, clientWidth: 640 }, loadEngine, onStatus: (status) => statuses.push(status),
    requestFrame: (fn) => { frames.set(++next, fn); return next; }, cancelFrame: (id) => frames.delete(id), observeResize: () => () => { stopped += 1; } });
  const frame = () => { const [id, fn] = frames.entries().next().value || []; if (fn) { frames.delete(id); fn(); } };
  return { owner, frame, statuses, frames, stopped: () => stopped };
}

test("P08 disposed lazy engine can never draw or report ready for a different owner", async () => {
  let resolve, draws = 0, purges = 0; const engine = { react: () => { draws += 1; }, purge: () => { purges += 1; }, relayout: () => {} };
  const harness = controller(() => new Promise((done) => { resolve = done; })), value = fixture();
  harness.owner.update(buildPlotlyFigure(value.chart, value.table)); harness.frame(); await turn(); harness.owner.dispose(); resolve(engine); await turn();
  assert.equal(draws, 0); assert.equal(purges, 1); assert.equal(harness.statuses.includes("ready"), false); assert.equal(harness.stopped(), 1); assert.equal(harness.frames.size, 0);
});

test("P08 serial rendering coalesces updates, isolates library mutations and closes unknown controls", async () => {
  let release, purges = 0; const draws = [], layouts = [], engine = { react: (node, data) => {
    draws.push(data[0].y[0]); data[0].y[0] = 999; return draws.length === 1 ? new Promise((done) => { release = done; }) : Promise.resolve();
  }, purge: () => { purges += 1; }, relayout: (node, fields) => { layouts.push(fields); } };
  const harness = controller(async () => engine), value = fixture(), figure = buildPlotlyFigure(value.chart, value.table), before = copy(figure);
  harness.owner.update(figure); harness.frame(); await turn();
  for (let number = 1; number <= 20; number += 1) { const newer = copy(figure); newer.data[0].y[0] = number; harness.owner.update(newer); }
  release(); await turn(); harness.frame(); await turn();
  assert.deepEqual(draws, [-1, 20]); assert.deepEqual(figure, before); assert.equal(value.table.rows[0].amount, -1);
  assert.equal(await harness.owner.control("https://outside.invalid"), false); assert.deepEqual(layouts, []);
  assert.equal(harness.statuses.filter((status) => status === "ready").length, 1); harness.owner.dispose(); assert.equal(purges, 1);
});
