import { exactCell, canonicalNumeric, compareExactNumeric } from "../../services/precisionCells.js";

export function formatCell(value, column, table = {}) {
  if (value == null) return "\u2014";
  if (column.type === "currency" && typeof value === "number") {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: column.currency || table.currency || "USD",
      maximumFractionDigits: column.fractionDigits ?? 0
    }).format(value);
  }
  if (column.type === "percentage" && typeof value === "number") {
    return `${new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value)}%`;
  }
  if (column.type === "number" && typeof value === "number") {
    return new Intl.NumberFormat("en-US", { maximumFractionDigits: 2 }).format(value);
  }
  if (column.type === "date" && typeof value === "string") {
    const date = new Date(`${value.slice(0, 10)}T12:00:00`);
    return Number.isNaN(date.valueOf()) ? value : new Intl.DateTimeFormat("en-US", {
      month: "short", day: "numeric", year: "numeric"
    }).format(date);
  }
  return String(value);
}

export function sortTableRows(table, sort) {
  if (!sort) return table.rows;
  return [...table.rows].sort((left, right) => {
    const a = left[sort.key], b = right[sort.key];
    if (a == null || b == null) return a == null ? (b == null ? 0 : 1) : -1;
    const precise = exactCell(table, left, sort.key) || exactCell(table, right, sort.key) ? compareExactNumeric(a, b) : null;
    const comparison = precise ?? (typeof a === "number" && typeof b === "number" ? a - b : String(a).localeCompare(String(b), undefined, { numeric: true }));
    return sort.direction === "asc" ? comparison : -comparison;
  });
}

function spreadsheetText(value) {
  const text = value == null ? "" : String(value);
  // Some spreadsheet importers ignore leading control/format characters. Test
  // the significant prefix, then put the literal marker before the whole value.
  const significant = text.replace(/^[\s\u0000-\u001f\u007f-\u009f\u200b-\u200f\u202a-\u202e\u2060-\u206f]*/u, "");
  return typeof value !== "number" && /^[=+\-@]/.test(significant) ? `'${text}` : text;
}

export function safeCsvCell(value, exact = false) {
  // Preserve real negative numbers. Text cannot select a spreadsheet formula.
  const safe = exact && canonicalNumeric(value) ? value : spreadsheetText(value);
  return `"${safe.replaceAll('"', '""')}"`;
}

/** One clipboard cell: delimiters inside data cannot create executable cells. */
export function safeTsvCell(value, exact = false) {
  // Clipboard consumers differ in their quoting support. Flatten row/column
  // controls first; CSV remains the lossless multiline export format.
  const flattened = typeof value === "number" ? value
    : (value == null ? "" : String(value)).replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/gu, " ");
  const safe = exact && canonicalNumeric(value) ? value : spreadsheetText(flattened);
  return safe.includes('"') ? `"${safe.replaceAll('"', '""')}"` : safe;
}

/** Copy numeric values as numbers; presentation formatting stays in the UI. */
export function createTsv(table, rows = table.rows) {
  return [
    table.columns.map((column) => safeTsvCell(column.label)).join("\t"),
    ...rows.map((row) => table.columns.map((column) => {
      const value = row[column.key];
      return safeTsvCell(typeof value === "number" ? value : formatCell(value, column, table), exactCell(table, row, column.key));
    }).join("\t"))
  ].join("\n");
}

export function createCsv(table, rows = table.rows) {
  return `\uFEFF${[
    table.columns.map((column) => safeCsvCell(column.label)).join(","),
    ...rows.map((row) => table.columns.map((column) => safeCsvCell(row[column.key], exactCell(table, row, column.key))).join(","))
  ].join("\r\n")}`;
}

// One headline number: a KPI card, a chart axis, a tooltip. Whole units,
// since an axis does not need cents. Uses the currency the response names
// (CZK for the bank), dollars when it names none.
export function formatMetric(value, type, currency) {
  if (type === "currency") {
    return new Intl.NumberFormat("en-US", {
      style: "currency", currency: currency || "USD", maximumFractionDigits: 0
    }).format(value);
  }
  if (type === "percentage") return `${value}%`;
  // Years and ids arrive as "string" columns: 1993, never "1,993".
  if (type === "string" || typeof value !== "number") return String(value);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value);
}
