import React, { useMemo, useState } from "react";
import { createCsv, createTsv, formatCell, sortTableRows } from "./financialValues.js";

const numericTypes = ["currency", "percentage", "number"];

export default function FinancialTable({ table }) {
  const [sort, setSort] = useState(null);
  const [feedback, setFeedback] = useState("");
  const rows = useMemo(() => sortTableRows(table, sort), [sort, table]);
  const updateSort = (key) => setSort((current) => current?.key === key
    ? { key, direction: current.direction === "asc" ? "desc" : "asc" } : { key, direction: "asc" });
  const copyTable = async () => {
    try {
      await navigator.clipboard.writeText(createTsv(table, rows));
      setFeedback("Table copied");
    } catch { setFeedback("Copy unavailable in this browser"); }
  };
  const downloadCsv = () => {
    let url;
    let anchor;
    try {
      url = URL.createObjectURL(new Blob([createCsv(table, rows)], { type: "text/csv;charset=utf-8" }));
      anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${table.id || "aqua-data"}.csv`;
      document.body.append(anchor);
      anchor.click();
      setFeedback("CSV downloaded");
    } catch { setFeedback("CSV export unavailable in this browser"); }
    finally {
      anchor?.remove();
      if (url) window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  };

  return (
    <section className="financial-table" aria-label={table.title}>
      <div className="financial-table__heading">
        <h3>{table.title}</h3>
        <div className="financial-table__actions">
          <button type="button" onClick={copyTable}>Copy table</button>
          <button type="button" onClick={downloadCsv}>Download CSV</button>
        </div>
      </div>
      <p className="action-feedback" role="status" aria-live="polite">{feedback}</p>
      <div className="financial-table__scroll" tabIndex={0} role="region" aria-label={`${table.title} table, scroll for more columns`}>
        <table>
          <thead><tr>{table.columns.map((column) => (
            <th key={column.key} scope="col" data-numeric={numericTypes.includes(column.type)}
              aria-sort={sort?.key === column.key ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
              <button type="button" className="sort-button" onClick={() => updateSort(column.key)} aria-label={`Sort by ${column.label}`}>
                {column.label}<span aria-hidden="true">{sort?.key === column.key ? (sort.direction === "asc" ? " ↑" : " ↓") : " ↕"}</span>
              </button>
            </th>
          ))}</tr></thead>
          <tbody>{rows.map((row, index) => (
            <tr key={`${table.id}-${index}`}>{table.columns.map((column) => (
              <td key={column.key} data-numeric={numericTypes.includes(column.type)}>{formatCell(row[column.key], column, table)}</td>
            ))}</tr>
          ))}</tbody>
        </table>
      </div>
    </section>
  );
}
