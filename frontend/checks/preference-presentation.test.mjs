import test from "node:test";
import assert from "node:assert/strict";
import { buildPlotlyFigure } from "../src/services/plotlyFigure.js";
import { dateOptions, formatTimestamp, numberOptions } from "../src/services/preferenceFormatting.js";
import { createCsv, createTsv, formatCell } from "../src/components/data/financialValues.js";
import { markExactCell } from "../src/services/precisionCells.js";
import { ACCOUNT_DEFAULTS, validateValues } from "../src/settings/schema.js";
import { plotlyFixture } from "./plotly-fixture.mjs";

test("locale and display precision change presentation while copy/export keep source amounts", () => {
  const table = { id: "amounts", columns: [{ key: "amount", label: "Amount", type: "currency", currency: "CZK" }],
    rows: [{ amount: -1234.56789 }, { amount: 0 }, { amount: null }] };
  const before = structuredClone(table), csv = createCsv(table), tsv = createTsv(table);
  for (const locale of ["en-US", "en-GB"]) for (const precision of ["0", "2", "4", "6"]) {
    const preferences = { ...ACCOUNT_DEFAULTS, locale, precision };
    assert.equal(formatCell(table.rows[0].amount, table.columns[0], table, preferences),
      new Intl.NumberFormat(locale, { style: "currency", currency: "CZK", maximumFractionDigits: Number(precision) }).format(-1234.56789));
    assert.equal(formatCell(0, { type: "number" }, table, preferences), "0");
    assert.equal(formatCell(null, table.columns[0], table, preferences), "—");
    assert.equal(createCsv(table), csv); assert.equal(createTsv(table), tsv);
  }
  assert.match(csv, /-1234\.56789/); assert.match(tsv, /-1234\.56789/);
  assert.deepEqual(table, before);
});

test("exact decimal provenance remains literal at every display precision and disables charts", () => {
  const exact = "9007199254740993.123456789", fixture = plotlyFixture({ rows: [{ label: "Exact", amount: exact }] });
  markExactCell(fixture.table, fixture.table.rows[0], "amount");
  const csv = createCsv(fixture.table);
  for (const precision of ["auto", "0", "2", "4", "6"]) {
    const preferences = { ...ACCOUNT_DEFAULTS, precision, palette: "diverging" };
    assert.equal(formatCell(exact, fixture.table.columns[1], fixture.table, preferences), exact);
    assert.equal(buildPlotlyFigure(fixture.descriptor, fixture.table, { preferences }), null);
    assert.equal(createCsv(fixture.table), csv);
  }
  assert.match(csv, /9007199254740993\.123456789/);
});

test("calendar dates never cross a day and source offset timestamps remain exact", () => {
  const column = { type: "date" }, value = "2026-10-28T00:01:02.123456+05:45";
  for (const timezone of ["UTC", "America/Chicago", "America/Los_Angeles", "Europe/London"]) {
    const preferences = { ...ACCOUNT_DEFAULTS, locale: "en-GB", date_style: "long", timezone };
    assert.equal(formatCell("2024-02-29", column, {}, preferences), "29 February 2024");
    assert.equal(formatCell(value, column, {}, preferences), value);
    assert.equal(formatCell("2025-02-29", column, {}, preferences), "2025-02-29");
    assert.equal(dateOptions(preferences, true).options.timeZone, "UTC");
  }
});

test("timestamp locale, timezone and hour-cycle preferences have actual formatting effects", () => {
  const instant = "2026-10-28T00:30:00Z";
  const utc = formatTimestamp(instant, { locale: "en-GB", timezone: "UTC", date_style: "short", time_format: "24" });
  const chicago = formatTimestamp(instant, { locale: "en-GB", timezone: "America/Chicago", date_style: "short", time_format: "24" });
  const twelve = formatTimestamp(instant, { locale: "en-US", timezone: "UTC", date_style: "medium", time_format: "12" });
  assert.match(utc, /28\/10\/2026.*00:30/);
  assert.match(chicago, /27\/10\/2026.*19:30/);
  assert.match(twelve, /12:30.*AM/i);
  assert.equal(formatTimestamp("not-a-timestamp", ACCOUNT_DEFAULTS), "not-a-timestamp");
  assert.equal(numberOptions({ locale: "javascript:bad", precision: "1000000" }, 4).digits, 4);
  assert.equal(numberOptions({ locale: "javascript:bad" }).locale, "en-US");
});

test("theme, palette, legend and grid choices never change plotted source values or engine permissions", () => {
  const { descriptor, table } = plotlyFixture({ type: "line" });
  const before = structuredClone({ descriptor, table }), csv = createCsv(table);
  for (const theme of ["opal", "light", "legacy"]) for (const palette of ["categorical", "sequential", "diverging"])
    for (const legend of ["auto", "show", "hide"]) for (const grid of ["subtle", "standard", "minimal"]) {
      const preferences = { ...ACCOUNT_DEFAULTS, palette, legend, grid, font: "system" };
      const figure = buildPlotlyFigure(descriptor, table, { theme, preferences });
      assert.ok(figure);
      assert.deepEqual(figure.data[0].y, [0, -12.5, null]);
      assert.equal(figure.data[0].connectgaps, false);
      assert.match(figure.data[0].marker.color, /^#[0-9a-f]{6}$/i);
      assert.equal(figure.layout.showlegend, legend === "show");
      assert.equal(figure.layout.yaxis.showgrid, grid !== "minimal");
      assert.equal(figure.layout.yaxis.gridwidth, grid === "standard" ? 2 : 1);
      assert.match(figure.layout.font.family, /^system-ui/);
      assert.equal(figure.config.showLink, false); assert.equal(figure.config.editable, false);
      assert.equal(figure.config.showSendToCloud, false); assert.equal(figure.config.sendData, false);
      assert.equal(figure.config.plotlyServerURL, ""); assert.equal(figure.config.topojsonURL, "");
    }
  assert.equal(createCsv(table), csv); assert.deepEqual({ descriptor, table }, before);
});

test("exploration preference changes revision behavior while motion remains explicitly bounded", () => {
  const { descriptor, table } = plotlyFixture();
  const kept = ["first", "next"].map(revisionKey => buildPlotlyFigure(descriptor, table,
    { preferences: { ...ACCOUNT_DEFAULTS, preserve_exploration: true }, revisionKey }));
  assert.equal(kept[0].layout.uirevision, kept[1].layout.uirevision);
  const reset = ["first", "next"].map(revisionKey => buildPlotlyFigure(descriptor, table,
    { preferences: { ...ACCOUNT_DEFAULTS, preserve_exploration: false }, revisionKey }));
  assert.notEqual(reset[0].layout.uirevision, reset[1].layout.uirevision);
  assert.equal(buildPlotlyFigure(descriptor, table, { animate: false }).layout.transition.duration, 0);
  assert.ok(buildPlotlyFigure(descriptor, table, { animate: true }).layout.transition.duration <= 150);
});

test("chart text scale enlarges readable labels and rejects coercion without changing values", () => {
  const { descriptor, table } = plotlyFixture(), before = structuredClone({ descriptor, table });
  const base = buildPlotlyFigure(descriptor, table, { textScale: 100 });
  const enlarged = buildPlotlyFigure(descriptor, table, { textScale: 150 });
  assert.equal(enlarged.layout.font.size, base.layout.font.size * 1.5);
  assert.equal(enlarged.layout.height, base.layout.height * 1.5);
  assert.deepEqual(enlarged.data[0].y, base.data[0].y);
  let coercions = 0;
  const hostile = { valueOf() { coercions++; return 150; }, toString() { coercions++; return "150"; } };
  for (const textScale of ["150", true, null, Infinity, -100, 1000000, hostile]) {
    const figure = buildPlotlyFigure(descriptor, table, { textScale });
    assert.equal(figure.layout.font.size, base.layout.font.size);
    assert.equal(figure.layout.height, base.layout.height);
  }
  assert.equal(coercions, 0);
  assert.deepEqual({ descriptor, table }, before);
});

test("foreign JSON chart preferences cannot select prototype properties, URLs or arbitrary engine configuration", () => {
  const { descriptor, table } = plotlyFixture();
  for (const foreign of ["constructor", "__proto__", "prototype", "https://foreign.invalid/style", "<script>alert(1)</script>"]) {
    assert.throws(() => validateValues({ ...ACCOUNT_DEFAULTS, palette: foreign }, "account"));
    const figure = buildPlotlyFigure(descriptor, table, { theme: foreign, preferences: {
      ...ACCOUNT_DEFAULTS, palette: foreign, font: foreign, grid: foreign, legend: foreign,
      config: { plotlyServerURL: "https://foreign.invalid" }, layout: { images: [{ source: "https://foreign.invalid" }] }
    } });
    assert.ok(figure);
    assert.match(figure.data[0].marker.color, /^#[0-9a-f]{6}$/i);
    assert.equal(JSON.stringify(figure).includes("foreign.invalid"), false);
    assert.equal(JSON.stringify(figure).includes("<script>"), false);
  }
});
