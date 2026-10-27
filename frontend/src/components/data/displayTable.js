const types = new Set(["string", "number", "currency", "percentage", "date"]);
const text = (value, limit) => typeof value === "string" && value.length <= limit;
const currency = (value) => value === undefined || typeof value === "string" && /^[A-Z]{3}$/.test(value);
const bytes = (value) => new TextEncoder().encode(JSON.stringify(value)).byteLength;
function record(value, allowed) {
  return value !== null && typeof value === "object" && [Object.prototype, null].includes(Object.getPrototypeOf(value))
    && Reflect.ownKeys(value).every((key) => typeof key === "string" && allowed.includes(key)
      && Object.hasOwn(Object.getOwnPropertyDescriptor(value, key), "value"));
}
function array(value, limit) {
  return Array.isArray(value) && Object.getPrototypeOf(value) === Array.prototype && value.length <= limit
    && Reflect.ownKeys(value).length === value.length + 1
    && Array.from({ length: value.length }, (_, index) => Object.getOwnPropertyDescriptor(value, String(index)))
      .every((descriptor) => descriptor && Object.hasOwn(descriptor, "value"));
}

/** Display validation keeps the original table/rows and exact-cell provenance. */
export function displayTable(table) {
  try {
    if (!record(table, ["id", "title", "columns", "rows", "currency"])
      || !(table.id === undefined || text(table.id, 80)) || !(table.title === undefined || text(table.title, 4000))
      || !currency(table.currency) || !array(table.columns, 64) || !table.columns.length || !array(table.rows, 1000)) return null;
    for (const column of table.columns) {
      if (!record(column, ["key", "label", "type", "currency", "fractionDigits"]) || !text(column.key, 256) || !column.key.length
        || !text(column.label, 256) || !types.has(column.type) || !currency(column.currency)
        || !(column.fractionDigits === undefined || Number.isSafeInteger(column.fractionDigits) && column.fractionDigits >= 0 && column.fractionDigits <= 6)) return null;
    }
    const keys = table.columns.map((column) => column.key);
    if (new Set(keys).size !== keys.length) return null;
    let size = bytes({ id: table.id, title: table.title, columns: table.columns, currency: table.currency }) + 16;
    if (size > 240000) return null;
    for (const row of table.rows) {
      if (!record(row, keys)) return null;
      size += 3;
      for (const key of keys) {
        if (!Object.hasOwn(row, key)) return null;
        const value = row[key];
        if (!(value === null || typeof value === "boolean" || text(value, 10000)
          || typeof value === "number" && Number.isFinite(value))) return null;
        size += bytes(key) + bytes(value) + 2;
        if (size > 240000) return null;
      }
    }
    return table;
  } catch { return null; }
}
