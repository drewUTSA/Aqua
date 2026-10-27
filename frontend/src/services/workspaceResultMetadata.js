import { canonicalNumeric, markExactCell } from "./precisionCells.js";
const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const require = (value) => { if (!value) throw new Error("workspace_invalid_response"); };
const keys = (value, expected) => record(value) && Object.keys(value).sort().join(",") === [...expected].sort().join(",");
const timestamp = (value) => typeof value === "string" && value.length <= 40 && Number.isFinite(Date.parse(value));

export function workspaceResultMetadata(response, metadata) {
  if (metadata === undefined) return response;
  require(response.status === "success" && keys(metadata, ["version", "source", "generated_at", "filters", "truncated", "max_rows", "aggregation", "column_units", "exact_values"])
    && metadata.version === 1 && keys(metadata.source, ["id", "freshness_at"]) && /^[0-9a-f]{64}$/.test(metadata.source.id)
    && (metadata.source.freshness_at === null || timestamp(metadata.source.freshness_at)) && timestamp(metadata.generated_at)
    && metadata.filters === null && typeof metadata.truncated === "boolean" && metadata.max_rows === 1000 && metadata.aggregation === "unknown"
    && record(metadata.column_units) && Array.isArray(metadata.exact_values) && metadata.exact_values.length <= 1024
    && new TextEncoder().encode(JSON.stringify(metadata)).byteLength <= 160000);
  require(response.tables.length <= 1 && (!response.tables.length || response.tables[0]?.id === "result"));
  const source = response.tables[0];
  require(!source || Array.isArray(source.columns) && source.columns.length <= 64 && Array.isArray(source.rows) && source.rows.length <= 1000);
  const columns = source?.columns.map((column) => column?.key) || [], declared = new Set(columns);
  require(columns.every((key) => typeof key === "string" && key.length <= 256) && declared.size === columns.length
    && Object.keys(metadata.column_units).length === declared.size && Object.entries(metadata.column_units).every(([key, value]) => declared.has(key) && value === null));
  if (!source) { require(!metadata.exact_values.length); return { ...response, resultMetadata: metadata }; }
  const table = { ...source, rows: source.rows.map((row) => { require(record(row)); return { ...row }; }) }, seen = new Set();
  for (const entry of metadata.exact_values) {
    require(keys(entry, ["row", "column", "value", "kind"]) && Number.isSafeInteger(entry.row) && entry.row >= 0 && entry.row < table.rows.length
      && declared.has(entry.column) && canonicalNumeric(entry.value) && ["decimal", "integer"].includes(entry.kind)
      && (entry.kind !== "integer" || /^-?(?:0|[1-9]\d*)$/.test(entry.value)));
    const cell = JSON.stringify([entry.row, entry.column]), row = table.rows[entry.row];
    require(!seen.has(cell) && Object.hasOwn(row, entry.column) && typeof row[entry.column] === "number" && Number.isFinite(row[entry.column]) && Number(entry.value) === row[entry.column]);
    seen.add(cell); row[entry.column] = entry.value; markExactCell(table, row, entry.column);
  }
  const exact = seen.size > 0;
  return { ...response, tables: [table], resultMetadata: metadata, ...(exact ? { visualizations: [], kpis: [],
    precisionNote: "Exact values are preserved in the table and export. Charts and headline metrics are unavailable for this result to avoid rounding." } : {}) };
}
