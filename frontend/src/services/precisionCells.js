// Provenance is bound to the normalized table and original row objects. Generic
// strings, cloned rows and unrelated tables retain normal spreadsheet escaping.
const tables = new WeakMap();
export const canonicalNumeric = (value) => typeof value === "string" && value.length <= 256 && /^-?(?:0|[1-9]\d*)(?:\.\d+)?$/.test(value);
export function markExactCell(table, row, column) {
  if (!tables.has(table)) tables.set(table, new WeakMap());
  const cells = tables.get(table); if (!cells.has(row)) cells.set(row, new Set()); cells.get(row).add(column);
}
export const exactCell = (table, row, column) => tables.get(table)?.get(row)?.has(column) === true && canonicalNumeric(row[column]);

function numericText(value) {
  if (canonicalNumeric(value)) return value;
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  const text = String(value); if (!text.includes("e")) return text;
  const [, sign, whole, fraction = "", exponent] = /^(-?)(\d+)(?:\.(\d+))?e([+-]?\d+)$/.exec(text);
  const digits = whole + fraction, point = whole.length + Number(exponent);
  return sign + (point <= 0 ? `0.${"0".repeat(-point)}${digits}` : point >= digits.length ? digits + "0".repeat(point - digits.length) : `${digits.slice(0, point)}.${digits.slice(point)}`);
}

// Compare displayed numeric values without rounding exact decimal strings into
// binary numbers. Number.toString peers expand only the finite JS exponent range.
export function compareExactNumeric(left, right) {
  const texts = [numericText(left), numericText(right)]; if (texts.some((value) => value === null)) return null;
  const parts = texts.map((value) => { const [whole, fraction = ""] = value.replace(/^-/, "").split(".");
    return { negative: value.startsWith("-") && /[1-9]/.test(whole + fraction), whole, fraction }; });
  const [a, b] = parts; if (a.negative !== b.negative) return a.negative ? -1 : 1;
  const length = Math.max(a.fraction.length, b.fraction.length), af = a.fraction.padEnd(length, "0"), bf = b.fraction.padEnd(length, "0");
  const comparison = Math.sign(a.whole.length - b.whole.length) || (a.whole > b.whole ? 1 : a.whole < b.whole ? -1 : 0) || (af > bf ? 1 : af < bf ? -1 : 0);
  return comparison === 0 ? 0 : a.negative ? -comparison : comparison;
}
