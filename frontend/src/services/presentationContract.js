import { exactCell } from "./precisionCells.js";
import { buildPlotlyFigure } from "./plotlyFigure.js";

export const PRESENTATION_REASONS = ["ordinary_text", "requested_visual", "visual_followup", "no_rows", "scalar_result", "unsupported_shape", "point_limit", "precision_limit", "ambiguous_units", "invalid_axis"];
const forbidden = new Set(["__proto__", "prototype", "constructor"]);
const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const require = (condition) => { if (!condition) throw new Error("presentation_invalid"); };
const text = (value, limit) => typeof value === "string" && value.length <= limit;
const exactKeys = (value, expected) => record(value) && Reflect.ownKeys(value).length === expected.length
  && Reflect.ownKeys(value).every((key) => typeof key === "string" && !forbidden.has(key) && expected.includes(key));
const integer = (value, minimum, maximum) => Number.isSafeInteger(value) && value >= minimum && value <= maximum;
const unit = (value) => value === null || value === "count" || typeof value === "string" && /^[A-Z]{3}$/.test(value);
const bytes = (value) => new TextEncoder().encode(JSON.stringify(value)).byteLength;

/** Validate bound data before exposing it to any chart engine. No object cells. */
export function validateVisualTable(table) {
  require(record(table) && Reflect.ownKeys(table).every((key) => ["id", "title", "columns", "rows", "currency"].includes(key))
    && text(table.id, 80) && (table.title === undefined || text(table.title, 4000))
    && (table.currency === undefined || typeof table.currency === "string" && /^[A-Z]{3}$/.test(table.currency))
    && Array.isArray(table.columns) && table.columns.length > 0 && table.columns.length <= 64
    && Array.isArray(table.rows) && table.rows.length <= 1000);
  const keys = table.columns.map((column) => {
    require(record(column) && Reflect.ownKeys(column).every((key) => ["key", "label", "type", "currency", "fractionDigits"].includes(key))
      && text(column.key, 256) && column.key.length > 0 && !forbidden.has(column.key)
      && text(column.label, 256) && ["string", "number", "currency", "percentage", "date"].includes(column.type)
      && (column.currency === undefined || typeof column.currency === "string" && /^[A-Z]{3}$/.test(column.currency))
      && (column.fractionDigits === undefined || integer(column.fractionDigits, 0, 6)));
    return column.key;
  });
  require(new Set(keys).size === keys.length);
  // Count bounded primitives incrementally; do not stringify a potentially huge
  // nested payload before establishing its shape and allocation ceiling.
  let size = bytes({ id: table.id, title: table.title, columns: table.columns, currency: table.currency }) + 16;
  for (const row of table.rows) {
    size += 3;
    require(record(row) && Reflect.ownKeys(row).every((key) => typeof key === "string" && keys.includes(key) && !forbidden.has(key)));
    for (const key of keys) {
      const value = row[key];
      require(value === null || typeof value === "boolean" || text(value, 10000)
        || typeof value === "number" && Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value)));
      require(!exactCell(table, row, key));
      size += bytes(key) + bytes(value) + 2;
      require(size <= 240000);
    }
  }
  return table;
}

/** A closed descriptor references authorized rows; Plotly configuration is local. */
export function validatePresentation(value, response) {
  require(exactKeys(value, ["version", "intent", "default_view", "reason", "charts"]) && value.version === 1
    && ["text", "explicit", "followup"].includes(value.intent) && ["summary", "table", "chart"].includes(value.default_view)
    && PRESENTATION_REASONS.includes(value.reason) && Array.isArray(value.charts) && value.charts.length <= 1);
  require(response?.status === "success" && Array.isArray(response.tables) && response.tables.length <= 1);
  require(value.default_view === "chart" ? value.charts.length === 1 && value.intent !== "text" : value.charts.length === 0);
  if (!value.charts.length) { require(bytes(value) <= 65536); return value; }
  require(!response.precisionNote && !response.resultMetadata?.exact_values?.length);
  for (const chart of value.charts) {
    require(exactKeys(chart, ["id", "type", "title", "tableId", "x", "series", "row_indices", "missing", "reduction", "input_rows", "output_points", "downsampled", "compatibility_key", "approximate"])
      && chart.id === "result-chart" && ["bar", "line"].includes(chart.type) && text(chart.title, 160)
      && chart.missing === "gap" && chart.reduction === "none" && chart.downsampled === false && chart.approximate === false
      && typeof chart.compatibility_key === "string" && /^[a-f0-9]{64}$/.test(chart.compatibility_key));
    const table = response.tables.find((item) => item.id === chart.tableId);
    validateVisualTable(table);
    require(exactKeys(chart.x, ["keys", "kind", "timezone", "calendar_parts"]) && Array.isArray(chart.x.keys)
      && integer(chart.x.keys.length, 1, 3) && new Set(chart.x.keys).size === chart.x.keys.length
      && ["category", "date", "datetime", "calendar"].includes(chart.x.kind)
      && (chart.x.kind === "datetime" ? chart.x.timezone === "UTC" : chart.x.timezone === null)
      && Array.isArray(chart.x.calendar_parts) && chart.x.calendar_parts.length <= 3);
    const combinations = ["year", "year,quarter", "year,month", "year,month,day"];
    require(chart.x.kind === "calendar" ? combinations.includes(chart.x.calendar_parts.join(",")) && chart.x.calendar_parts.length === chart.x.keys.length
      : chart.x.calendar_parts.length === 0 && (chart.x.kind === "category" || chart.x.keys.length === 1));
    require(Array.isArray(chart.series) && integer(chart.series.length, 1, 2) && chart.series.every((series) =>
      exactKeys(series, ["key", "label", "unit"]) && text(series.key, 256) && text(series.label, 80) && unit(series.unit)));
    const columns = new Set(table.columns.map((column) => column.key)), selected = [...chart.x.keys, ...chart.series.map((series) => series.key)];
    require(selected.every((key) => columns.has(key) && !forbidden.has(key)) && new Set(selected).size === selected.length);
    require(chart.series.length === 1 || chart.series[0].unit !== null && chart.series[0].unit === chart.series[1].unit);
    require(chart.input_rows === table.rows.length && chart.input_rows > 0 && chart.input_rows <= (chart.type === "bar" ? 50 : 500)
      && chart.output_points === chart.input_rows * chart.series.length && chart.output_points <= 500
      && Array.isArray(chart.row_indices) && chart.row_indices.length === chart.input_rows
      && new Set(chart.row_indices).size === chart.input_rows && chart.row_indices.every((index) => integer(index, 0, table.rows.length - 1)));
    for (const row of table.rows) for (const series of chart.series) require(row[series.key] === null || typeof row[series.key] === "number" && Number.isFinite(row[series.key]));
    require(buildPlotlyFigure(chart, table) !== null);
  }
  require(bytes(value) <= 65536);
  return value;
}

export function workspacePresentation(response, raw) {
  if (raw === undefined) return response;
  try { return { ...response, presentation: validatePresentation(raw, response) }; }
  catch (error) {
    if (error.message !== "presentation_invalid") throw error;
    return { ...response, presentation: null, presentationError: "This visual is unavailable. The saved table remains available." };
  }
}
