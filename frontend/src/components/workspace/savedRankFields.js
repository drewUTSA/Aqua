// The server supplies only a bounded, non-executable form hint after checking
// ownership and data access. Employees never receive the underlying statement.
export function savedRankFields(value) {
  const keys = ["source", "group", "measure", "field", "direction", "number", "ties"];
  if (!value || typeof value !== "object" || Array.isArray(value)
    || Object.keys(value).length !== keys.length || !keys.every(key => typeof value[key] === "string")) return null;
  const label = text => text.length <= 64 && /^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$/.test(text);
  if (!label(value.source) || !label(value.group) || !["count", "total"].includes(value.measure)
    || (value.measure === "total" ? !label(value.field) || value.field === value.group : value.field !== "")
    || !["top", "bottom"].includes(value.direction) || !/^[1-9][0-9]{0,2}$/.test(value.number) || value.ties !== "") return null;
  return Object.fromEntries(keys.map(key => [key, value[key]]));
}
