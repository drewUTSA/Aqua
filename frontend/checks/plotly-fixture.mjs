export function plotlyFixture({ type = "bar", rows = [{ label: "Zero", amount: 0 }, { label: "Negative", amount: -12.5 }, { label: "Missing", amount: null }] } = {}) {
  const table = { id: "result", columns: [{ key: "label", label: "Category", type: "string" }, { key: "amount", label: "Amount", type: "number" }], rows };
  const descriptor = { id: "result-chart", type, title: "Amount by category", tableId: "result", x: { keys: ["label"], kind: "category", timezone: null, calendar_parts: [] },
    series: [{ key: "amount", label: "Amount", unit: null }], row_indices: rows.map((_, index) => index), missing: "gap", reduction: "none",
    input_rows: rows.length, output_points: rows.length, downsampled: false, compatibility_key: "a".repeat(64), approximate: false };
  return { table, descriptor };
}
