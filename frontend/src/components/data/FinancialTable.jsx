import React, { useMemo, useState } from "react";
import { createCsv, createTsv, formatCell, sortTableRows } from "./financialValues.js";
import { displayTable } from "./displayTable.js";

const numericTypes = ["currency", "percentage", "number"];

export default function FinancialTable({ table, preferences }) {
  const safe = displayTable(table);
  if (!safe) return <p className="financial-table-unavailable" role="status">This result table is unavailable because its data is invalid or exceeds the display limit.</p>;
  return <TableContents table={safe} preferences={preferences} />;
}

function TableContents({ table, preferences }) {
  const [sort, setSort] = useState(null);
  const [feedback, setFeedback] = useState("");
  const [page, setPage] = useState(0), [fullPrecision, setFullPrecision] = useState(false);
  const rows = useMemo(() => sortTableRows(table, sort), [sort, table]);
  const pageSize = preferences && [10, 25, 50].includes(preferences.table_page_size) ? preferences.table_page_size : Math.max(1, rows.length);
  const pages = Math.max(1, Math.ceil(rows.length / pageSize)), currentPage = Math.min(page, pages - 1);
  const visible = rows.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
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
    <section className="financial-table" data-density={preferences?.table_density} aria-label={table.title || "Results"}>
      <div className="financial-table__heading">
        <h3>{table.title || "Results"}</h3>
        <div className="financial-table__actions">
          <button type="button" onClick={copyTable}>Copy table</button>
          <button type="button" onClick={downloadCsv}>Download CSV</button>
          {preferences && <button type="button" aria-pressed={fullPrecision} onClick={() => setFullPrecision((value) => !value)}>{fullPrecision ? "Use display precision" : "Show full precision"}</button>}
        </div>
      </div>
      <p className="action-feedback" role="status" aria-live="polite">{feedback}</p>
      <div className="financial-table__scroll" tabIndex={0} role="region" aria-label={`${table.title || "Results"} table, scroll for more columns`}>
        <table>
          <thead><tr>{table.columns.map((column) => (
            <th key={column.key} scope="col" data-numeric={numericTypes.includes(column.type)}
              aria-sort={sort?.key === column.key ? (sort.direction === "asc" ? "ascending" : "descending") : "none"}>
              <button type="button" className="sort-button" onClick={() => updateSort(column.key)} aria-label={`Sort by ${column.label}`}>
                {column.label}<span aria-hidden="true">{sort?.key === column.key ? (sort.direction === "asc" ? " ↑" : " ↓") : " ↕"}</span>
              </button>
            </th>
          ))}</tr></thead>
          <tbody>{visible.map((row, index) => (
            <tr key={`${table.id}-${index}`}>{table.columns.map((column) => (
              <td key={column.key} data-numeric={numericTypes.includes(column.type)} title={row[column.key] == null ? undefined : String(row[column.key])}>{fullPrecision && row[column.key] != null ? String(row[column.key]) : formatCell(row[column.key], column, table, preferences)}</td>
            ))}</tr>
          ))}</tbody>
        </table>
      </div>
      {pages > 1 && <nav className="financial-table__pagination" aria-label="Result table pages">
        <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous rows</button>
        <span role="status">Page {currentPage + 1} of {pages} · {rows.length} returned rows</span>
        <button type="button" disabled={currentPage === pages - 1} onClick={() => setPage(currentPage + 1)}>Next rows</button>
        <p>Copy and CSV include all returned rows, with source precision.</p>
      </nav>}
    </section>
  );
}
