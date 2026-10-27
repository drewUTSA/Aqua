import { exactCell } from "./precisionCells.js";

const forbidden = new Set(["__proto__", "constructor", "prototype"]);
const record = (value) => value !== null && typeof value === "object" && [Object.prototype, null].includes(Object.getPrototypeOf(value));
const properties = (value) => record(value) && Reflect.ownKeys(value).every((key) => typeof key === "string" && !forbidden.has(key));
const keys = (value, expected) => properties(value) && Reflect.ownKeys(value).sort().join(",") === [...expected].sort().join(",");
const text = (value, max) => typeof value === "string" && value.length > 0 && value.length <= max;
const numeric = (value) => typeof value === "number" && Number.isFinite(value) && (!Number.isInteger(value) || Number.isSafeInteger(value));
const own = (row, key) => record(row) && Object.hasOwn(row, key);
const bytes = (value) => new TextEncoder().encode(JSON.stringify(value)).byteLength;
const shortened = (value, limit) => { const points = Array.from(value); return points.length <= limit ? value : points.slice(0, limit - 1).join("") + "…"; };
export const plotlyLiteral = (value) => String(value).replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#39;");
const palettes = {
  opal: { text: "#f2f1ed", muted: "#adb0ba", grid: "#37383f", colors: ["#cdc8ec", "#82dbca"] },
  legacy: { text: "#edf8fc", muted: "#c6e0eb", grid: "#375363", colors: ["#b9e8f0", "#91b6ff"] }
};
const chartKeys = ["id", "type", "title", "tableId", "x", "series", "row_indices", "missing", "reduction", "input_rows", "output_points", "downsampled", "compatibility_key", "approximate"];
const calendars = [[], ["year"], ["year", "quarter"], ["year", "month"], ["year", "month", "day"]];

function calendarLabel(values, parts) {
  if (!values.every(Number.isSafeInteger)) return null;
  const [year, second, day] = values;
  if (year < 1 || year > 9999) return null;
  const prefix = String(year).padStart(4, "0");
  if (parts.length === 1) return prefix;
  if (parts[1] === "quarter") return second >= 1 && second <= 4 ? `${prefix}-Q${second}` : null;
  if (second < 1 || second > 12) return null;
  const month = `${prefix}-${String(second).padStart(2, "0")}`;
  if (parts.length === 2) return month;
  const label = `${month}-${String(day).padStart(2, "0")}`;
  return validDate(label) ? label : null;
}
function validDate(value) {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith("0000")) return false;
  const time = Date.parse(`${value}T00:00:00Z`);
  return Number.isFinite(time) && new Date(time).toISOString().slice(0, 10) === value;
}
function xValue(row, axis) {
  const values = axis.keys.map((key) => row[key]);
  if (axis.kind === "category") {
    if (!values.every((value) => typeof value === "string" && value.length <= 256 || numeric(value))) return null;
    return values.map(String).join(" · ");
  }
  if (axis.kind === "calendar") return calendarLabel(values, axis.calendar_parts);
  if (axis.kind === "date") return validDate(values[0]) ? values[0] : null;
  const value = values[0];
  const match = typeof value === "string" && value.length <= 40 && /^(\d{4}-\d{2}-\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || !validDate(match[1]) || Number(match[2]) > 23 || Number(match[3]) > 59 || Number(match[4]) > 59
    || /[1-9]/.test((match[5] || "").slice(3)) || match[6] !== "Z" && (Number(match[6].slice(1, 3)) > 23 || Number(match[6].slice(4)) > 59)) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return null;
  const utc = new Date(time).toISOString();
  return /^\d{4}-/.test(utc) && !utc.startsWith("0000") ? utc : null;
}

/** Project an allowlisted result descriptor into fresh app-owned Plotly input. */
export function buildPlotlyFigure(descriptor, table, { theme = "opal" } = {}) {
  if (!keys(descriptor, chartKeys) || descriptor.id !== "result-chart" || !["bar", "line"].includes(descriptor.type)
    || !text(descriptor.title, 160) || descriptor.tableId !== "result" || !properties(table) || table.id !== "result"
    || !Array.isArray(table.columns) || table.columns.length > 64 || !Array.isArray(table.rows) || table.rows.length > 1000
    || !keys(descriptor.x, ["keys", "kind", "timezone", "calendar_parts"]) || !Array.isArray(descriptor.x.keys)
    || descriptor.x.keys.length < 1 || descriptor.x.keys.length > 3 || new Set(descriptor.x.keys).size !== descriptor.x.keys.length
    || !["category", "date", "datetime", "calendar"].includes(descriptor.x.kind)
    || !Array.isArray(descriptor.x.calendar_parts) || descriptor.x.calendar_parts.length > 3 || !descriptor.x.calendar_parts.every((part) => typeof part === "string")
    || !calendars.some((parts) => parts.join(",") === descriptor.x.calendar_parts.join(","))
    || !Array.isArray(descriptor.series) || descriptor.series.length < 1 || descriptor.series.length > 2
    || !Array.isArray(descriptor.row_indices) || descriptor.row_indices.length < 1
    || descriptor.missing !== "gap" || descriptor.reduction !== "none" || descriptor.downsampled !== false || descriptor.approximate !== false
    || descriptor.input_rows !== table.rows.length || descriptor.row_indices.length !== table.rows.length
    || descriptor.output_points !== descriptor.row_indices.length * descriptor.series.length || descriptor.output_points > 500
    || descriptor.type === "bar" && descriptor.row_indices.length > 50 || !text(descriptor.compatibility_key, 64) || !/^[0-9a-f]{64}$/.test(descriptor.compatibility_key)) return null;
  const axis = descriptor.x, temporal = ["date", "datetime"].includes(axis.kind);
  if ((axis.kind === "datetime" ? axis.timezone !== "UTC" : axis.timezone !== null)
    || (axis.kind === "calendar" ? !axis.calendar_parts.length || axis.calendar_parts.length !== axis.keys.length : axis.calendar_parts.length !== 0)
    || temporal && axis.keys.length !== 1) return null;
  const columns = new Map(table.columns.map((column) => [column?.key, column]));
  if (columns.size !== table.columns.length || !table.columns.every((column) => properties(column) && text(column.key, 256) && !forbidden.has(column.key) && text(column.label, 256))
    || !axis.keys.every((key) => text(key, 256) && columns.has(key))
    || !descriptor.series.every((series) => keys(series, ["key", "label", "unit"]) && text(series.key, 256) && columns.has(series.key)
      && !axis.keys.includes(series.key) && text(series.label, 80) && (series.unit === null || series.unit === "count" || typeof series.unit === "string" && /^[A-Z]{3}$/.test(series.unit)))
    || new Set(descriptor.series.map((series) => series.key)).size !== descriptor.series.length
    || descriptor.series.length > 1 && (!descriptor.series[0].unit || descriptor.series[0].unit !== descriptor.series[1].unit)) return null;
  let inputBytes = 0;
  for (const row of table.rows) {
    if (!properties(row) || Object.keys(row).length !== columns.size) return null;
    for (const key of columns.keys()) {
      const value = row[key];
      if (!Object.hasOwn(row, key) || exactCell(table, row, key)
        || !(value === null || typeof value === "boolean" || numeric(value) || typeof value === "string" && value.length <= 10000)) return null;
      inputBytes += typeof value === "string" ? new TextEncoder().encode(value).byteLength : 8;
      if (inputBytes > 240000) return null;
    }
  }
  const indices = descriptor.row_indices;
  if (new Set(indices).size !== indices.length || !indices.every((index) => Number.isSafeInteger(index) && index >= 0 && index < table.rows.length)
    || axis.kind === "category" && indices.some((index, position) => index !== position)) return null;
  const rows = indices.map((index) => table.rows[index]);
  if (!rows.every((row) => [...axis.keys, ...descriptor.series.map((series) => series.key)].every((key) => own(row, key) && !exactCell(table, row, key)))) return null;
  const values = rows.map((row) => xValue(row, axis));
  const identities = rows.map((row) => JSON.stringify(axis.keys.map((key) => row[key])));
  if (values.some((value) => value === null) || new Set(identities).size !== identities.length) return null;
  if (temporal && values.some((value, index) => index && Date.parse(value) <= Date.parse(values[index - 1]))) return null;
  if (axis.kind === "calendar" && values.some((value, index) => index && value <= values[index - 1])) return null;
  if (!descriptor.series.every((series) => rows.some((row) => row[series.key] !== null)
    && rows.every((row) => row[series.key] === null || numeric(row[series.key])))) return null;
  const palette = palettes[theme] || palettes.opal, labels = values.map((value, index) => plotlyLiteral(axis.kind === "datetime" ? rows[index][axis.keys[0]] : value)), slots = rows.map((_, index) => `row-${index}`);
  const tickLabels = values.map((value) => plotlyLiteral(shortened(value, 48)));
  const data = descriptor.series.map((series, index) => ({
    type: descriptor.type === "bar" ? "bar" : "scatter",
    ...(descriptor.type === "line" ? { mode: "lines+markers", connectgaps: false, line: { color: palette.colors[index], width: 2, shape: "linear" } } : {}),
    name: plotlyLiteral(series.label), x: temporal ? [...values] : [...slots], y: rows.map((row) => row[series.key]),
    marker: { color: palette.colors[index], size: 6 },
    customdata: rows.map((row, rowIndex) => [labels[rowIndex], row[series.key] === null ? "Missing" : plotlyLiteral(String(row[series.key])), plotlyLiteral(series.unit || "Unit not specified")]),
    hovertemplate: "%{customdata[0]}<br>%{customdata[1]} · %{customdata[2]}<extra>%{fullData.name}</extra>"
  }));
  const axisTitle = axis.keys.map((key) => columns.get(key)?.label || key).join(" · ");
  const unit = descriptor.series[0].unit;
  const layout = {
    autosize: true, height: 320, paper_bgcolor: "rgba(0,0,0,0)", plot_bgcolor: "rgba(0,0,0,0)",
    font: { family: "Manrope, system-ui, sans-serif", size: 12, color: palette.text },
    margin: { t: 24, r: 20, b: 70, l: 76 }, showlegend: data.length > 1, barmode: "group", dragmode: "zoom",
    legend: { orientation: "h", x: 0, y: 1.14, font: { color: palette.text } },
    xaxis: { type: temporal ? "date" : "category", title: { text: plotlyLiteral(shortened(axisTitle, 80)) }, automargin: true,
      gridcolor: palette.grid, zeroline: false, tickfont: { color: palette.muted },
      ...(temporal ? { tickformat: axis.kind === "date" ? "%Y-%m-%d" : "%Y-%m-%d<br>%H:%M UTC" }
        : { categoryorder: "array", categoryarray: [...slots], tickmode: "array", tickvals: [...slots], ticktext: [...tickLabels] }) },
    yaxis: { type: "linear", title: { text: plotlyLiteral(unit || "Unit not specified") }, automargin: true,
      gridcolor: palette.grid, zeroline: true, zerolinecolor: palette.muted, tickfont: { color: palette.muted } },
    hoverlabel: { bgcolor: theme === "legacy" ? "#0b2533" : "#191a1e", bordercolor: palette.muted, font: { color: palette.text } },
    transition: { duration: 0 }, uirevision: descriptor.compatibility_key, selectionrevision: descriptor.compatibility_key
  };
  const config = {
    displayModeBar: false, modeBarButtons: [], displaylogo: false, showLink: false, showSendToCloud: false,
    sendData: false, editable: false, editSelection: false, typesetMath: false, scrollZoom: false,
    responsive: false, doubleClick: "reset", locale: "en-US", plotlyServerURL: "", topojsonURL: ""
  };
  const figure = { data, layout, config };
  return bytes(figure) <= 240000 ? figure : null;
}
