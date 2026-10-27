import test from "node:test";
import assert from "node:assert/strict";
import { buildPlotlyFigure } from "../src/services/plotlyFigure.js";
import { markExactCell } from "../src/services/precisionCells.js";
import { createCsv } from "../src/components/data/financialValues.js";
import { plotlyFixture } from "./plotly-fixture.mjs";

test("bar and line preserve zero, negative and missing values without joining gaps", () => {
  for (const type of ["bar", "line"]) {
    const { descriptor, table } = plotlyFixture({ type });
    const figure = buildPlotlyFigure(descriptor, table);
    assert.deepEqual(figure.data[0].y, [0, -12.5, null]);
    assert.deepEqual(figure.data[0].x, ["row-0", "row-1", "row-2"]);
    assert.equal(figure.data[0].type, type === "bar" ? "bar" : "scatter");
    if (type === "line") assert.equal(figure.data[0].connectgaps, false);
    assert.equal(figure.layout.yaxis.zeroline, true);
  }
});

test("engine inputs are detached from table, descriptor, CSV and future updates", () => {
  const { descriptor, table } = plotlyFixture(), csv = createCsv(table), before = structuredClone({ descriptor, table });
  const first = buildPlotlyFigure(descriptor, table), next = buildPlotlyFigure(descriptor, table);
  first.data[0].y[0] = 900; first.data[0].x[0] = "Changed"; first.layout.xaxis.ticktext[0] = "Changed";
  assert.deepEqual({ descriptor, table }, before); assert.equal(createCsv(table), csv); assert.equal(next.data[0].y[0], 0);
});

test("duplicate joined category labels remain distinct source tuple positions", () => {
  const { descriptor, table } = plotlyFixture({ rows: [{ label: "a · b", second: "c", amount: 1 }, { label: "a", second: "b · c", amount: 2 }] });
  table.columns.push({ key: "second", label: "Second", type: "string" }); descriptor.x.keys.push("second");
  const figure = buildPlotlyFigure(descriptor, table);
  assert.deepEqual(figure.layout.xaxis.ticktext, ["a · b · c", "a · b · c"]);
  assert.deepEqual(figure.data[0].x, ["row-0", "row-1"]);
  table.rows[1].label = table.rows[0].label; table.rows[1].second = table.rows[0].second;
  assert.equal(buildPlotlyFigure(descriptor, table), null);
});

test("long category labels keep full hover/table text and do not let unrelated descriptions disable charts", () => {
  const value = "😀".repeat(100), { descriptor, table } = plotlyFixture({ rows: [{ label: value, amount: 1, description: "a".repeat(10000) }] });
  table.columns.push({ key: "description", label: "Description" });
  const figure = buildPlotlyFigure(descriptor, table);
  assert.equal(Array.from(figure.layout.xaxis.ticktext[0]).length, 48);
  assert.equal(figure.layout.xaxis.ticktext[0].endsWith("…"), true);
  assert.equal(figure.data[0].customdata[0][0], value); assert.equal(table.rows[0].label, value);
});

test("dates retain calendar day and UTC instants across timezone offsets", () => {
  const { descriptor, table } = plotlyFixture({ type: "line", rows: [{ label: "2024-02-29", amount: 0 }, { label: "2024-03-01", amount: 1 }] });
  descriptor.x.kind = "date";
  assert.deepEqual(buildPlotlyFigure(descriptor, table).data[0].x, ["2024-02-29", "2024-03-01"]);
  table.rows[0].label = "2024-02-30"; assert.equal(buildPlotlyFigure(descriptor, table), null);
  table.rows[0].label = "2024-03-10T06:59:00Z"; table.rows[1].label = "2024-03-10T07:01:00Z";
  descriptor.x.kind = "datetime"; descriptor.x.timezone = "UTC";
  const figure = buildPlotlyFigure(descriptor, table); assert.match(figure.layout.xaxis.tickformat, /UTC/);
  assert.equal(figure.data[0].x[0], "2024-03-10T06:59:00.000Z");
  table.rows[0].label = "2024-03-10T06:59:00"; assert.equal(buildPlotlyFigure(descriptor, table), null);
  table.rows[0].label = "2024-03-10T01:59:00-05:00";
  const offset = buildPlotlyFigure(descriptor, table);
  assert.equal(offset.data[0].x[0], "2024-03-10T06:59:00.000Z");
  assert.equal(offset.data[0].customdata[0][0], "2024-03-10T01:59:00-05:00");
  table.rows[0].label = "2024-03-10T06:59:00.123001Z"; assert.equal(buildPlotlyFigure(descriptor, table), null);
});

test("calendar parts validate real dates and never treat year numbers as amounts", () => {
  const { descriptor, table } = plotlyFixture({ type: "line", rows: [{ year: 2024, month: 2, day: 29, amount: 3 }] });
  table.columns = ["year", "month", "day", "amount"].map((key) => ({ key, label: key }));
  descriptor.x = { keys: ["year", "month", "day"], kind: "calendar", timezone: null, calendar_parts: ["year", "month", "day"] };
  assert.deepEqual(buildPlotlyFigure(descriptor, table).layout.xaxis.ticktext, ["2024-02-29"]);
  table.rows[0].year = 2023; assert.equal(buildPlotlyFigure(descriptor, table), null);
  table.rows[0] = { year: 2024, quarter: 1, amount: 3 };
  table.columns = ["year", "quarter", "amount"].map((key) => ({ key, label: key }));
  descriptor.x.keys = descriptor.x.calendar_parts = ["year", "quarter"];
  assert.deepEqual(buildPlotlyFigure(descriptor, table).layout.xaxis.ticktext, ["2024-Q1"]);
});

test("whole-result exact provenance and unsafe numeric coordinates remain table-only", () => {
  const { descriptor, table } = plotlyFixture();
  table.columns.push({ key: "record_id", label: "Record ID" });
  table.rows.forEach((row, index) => { row.record_id = String(index); });
  table.rows[0].record_id = "9007199254740993"; markExactCell(table, table.rows[0], "record_id");
  assert.equal(buildPlotlyFigure(descriptor, table), null);
  for (const value of ["0.1", Number.MAX_SAFE_INTEGER + 1, Infinity, NaN, {}, [1]]) {
    const fixture = plotlyFixture(); fixture.table.rows[0].amount = value;
    assert.equal(buildPlotlyFigure(fixture.descriptor, fixture.table), null);
  }
  const ordinary = plotlyFixture(); ordinary.table.rows[0].amount = 0.1;
  assert.equal(buildPlotlyFigure(ordinary.descriptor, ordinary.table).data[0].y[0], 0.1);
});

test("point limits never silently sample, aggregate or truncate", () => {
  for (const [type, count, expected] of [["bar", 50, true], ["bar", 51, false], ["line", 500, true], ["line", 501, false]]) {
    const { descriptor, table } = plotlyFixture({ type, rows: Array.from({ length: count }, (_, index) => ({ label: String(index), amount: index })) });
    assert.equal(Boolean(buildPlotlyFigure(descriptor, table)), expected);
  }
  const { descriptor, table } = plotlyFixture(); descriptor.row_indices.pop(); descriptor.output_points -= 1;
  assert.equal(buildPlotlyFigure(descriptor, table), null);
});

test("two series need the same proven unit and preserve missing cells", () => {
  const { descriptor, table } = plotlyFixture(); table.columns.push({ key: "second", label: "Second" });
  table.rows.forEach((row) => { row.second = 12; }); descriptor.series[0].unit = "USD";
  descriptor.series.push({ key: "second", label: "Second", unit: "USD" }); descriptor.output_points *= 2;
  assert.equal(buildPlotlyFigure(descriptor, table).data.length, 2);
  descriptor.series[1].unit = "EUR"; assert.equal(buildPlotlyFigure(descriptor, table), null);
  descriptor.series[1].unit = null; assert.equal(buildPlotlyFigure(descriptor, table), null);
});

test("theme changes restyle fresh figures while compatibility alone preserves view", () => {
  const { descriptor, table } = plotlyFixture();
  const opal = buildPlotlyFigure(descriptor, table), legacy = buildPlotlyFigure(descriptor, table, { theme: "legacy" });
  assert.notEqual(opal.data[0].marker.color, legacy.data[0].marker.color);
  assert.equal(opal.layout.uirevision, legacy.layout.uirevision);
  descriptor.compatibility_key = "b".repeat(64);
  assert.notEqual(buildPlotlyFigure(descriptor, table).layout.uirevision, opal.layout.uirevision);
  assert.equal(opal.layout.transition.duration, 0); assert.equal(legacy.layout.transition.duration, 0);
});
