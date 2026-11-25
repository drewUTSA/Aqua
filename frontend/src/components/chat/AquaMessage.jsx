import React, { useEffect, useRef, useState } from "react";
import SafeMarkdown from "./SafeMarkdown.js";
import FinancialTable from "../data/FinancialTable.jsx";
import ResultMetadata from "../data/ResultMetadata.jsx";
import { isSavedResultCandidate } from "../../features/resultCompanion/reference.js";

// Every answer shows the exact SQL behind it; a refused query shows the SQL
// that was blocked, so the user can see why.
function SqlBlock({ sql, label = "SQL" }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef(null);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  if (!sql) return null;

  const copySql = async () => {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      window.clearTimeout(timer.current);
      timer.current = window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  };

  return (
    <details className="sql-block">
      <summary>{label}</summary>
      <pre><code>{sql}</code></pre>
      <button type="button" className="text-action" onClick={copySql}>{copied ? "Copied" : "Copy SQL"}</button>
    </details>
  );
}

export default function AquaMessage({ message, hidden = false, onRetry, onRankAction, onConfirmCash, onOpenCash, onShowVisual, onUnderstandResult, preferences }) {
  const [copyStatus, setCopyStatus] = useState("");
  const copyTimer = useRef(null);
  useEffect(() => () => window.clearTimeout(copyTimer.current), []);
  const response = message.response || {};

  const copyResponse = async () => {
    try {
      await navigator.clipboard.writeText(response.message || "");
      setCopyStatus("Response copied");
      window.clearTimeout(copyTimer.current);
      copyTimer.current = window.setTimeout(() => setCopyStatus(""), 1800);
    } catch {
      setCopyStatus("Copy unavailable in this browser");
    }
  };

  if (response.status === "loading") {
    return (
      <article className={`message message--aqua${hidden ? " message--forming" : ""}`} data-message-id={message.id} aria-hidden={hidden || undefined} inert={hidden || undefined}>
        <div className="message__bubble message__bubble--aqua aqua-loading">
          <span className="status-mark" aria-hidden="true">AQUA</span>
          <span>{message.historical ? "Analysis status is shown below." : "AQUA is thinking…"}</span>
        </div>
      </article>
    );
  }

  if (response.status === "error") {
    return (
      <article className={`message message--aqua${hidden ? " message--forming" : ""}`} data-message-id={message.id} aria-hidden={hidden || undefined} inert={hidden || undefined}>
        <div className="message__bubble message__bubble--aqua error-card">
          <span className="status-mark" aria-hidden="true">AQUA</span>
          {message.previousSourceAvailable ? (
            <p><a href={`/api/v1/chats/${message.conversationId}/messages/${message.id}/previous-source`}
              target="_blank" rel="noopener noreferrer">Open saved answer from the previous data source</a></p>
          ) : <p>{response.error?.message || "AQUA couldn't complete that request. Please try again."}</p>}
          <SqlBlock sql={response.sql} label="SQL that was not run" />
          {response.error?.retryable && (
            <button type="button" className="text-action" onClick={() => onRetry(message.id)}>
              Try again
            </button>
          )}
          {onRankAction && <button type="button" className="text-action" onClick={onRankAction}>Rank groups in a new chat</button>}
        </div>
      </article>
    );
  }

  return (
    <article className={`message message--aqua${hidden ? " message--forming" : ""}`} data-message-id={message.id} aria-hidden={hidden || undefined} inert={hidden || undefined}>
      <div className="message__bubble message__bubble--aqua">
        <span className="status-mark" aria-label="AQUA response">AQUA</span>
        <div className="markdown-response">
          <SafeMarkdown>{response.message || ""}</SafeMarkdown>
          {response.status === "stopped" && <p role="status">Response stopped.</p>}
        </div>
        <SqlBlock sql={response.sql} />
        {(response.tables?.length > 0 || response.visualizations?.length > 0 || response.kpis?.length > 0) && (
          <div className="response-data">
            <ResultMetadata response={response} preferences={preferences?.account} />
            {response.presentationError && <p role="status">{response.presentationError}</p>}
            {response.tables?.map((table, index) => <FinancialTable key={`${typeof table?.id === "string" ? table.id : "unavailable"}:${index}`} table={table} preferences={preferences?.account} />)}
            {onShowVisual && response.tables?.length > 0 && <button type="button" className="text-action visual-result-open" onClick={() => onShowVisual(message.id)}>Show visuals</button>}
          </div>
        )}
        {(response.status !== "stopped" || response.message) && <div className="response-actions">
          {onUnderstandResult && isSavedResultCandidate(message) && <button type="button" className="text-action" data-understand-result onClick={() => onUnderstandResult(message.id)}>Understand this result</button>}
          {onRankAction && <button type="button" className="text-action" data-rank-ties onClick={onRankAction}>Choose tie rules in a new chat</button>}
          {onConfirmCash && <button type="button" className="text-action" data-confirm-cash onClick={onConfirmCash}>Confirm and calculate</button>}
            {onOpenCash && <button type="button" className="text-action" data-open-blank-cash aria-haspopup="dialog" onClick={onOpenCash}>Open cash calculator</button>}
          <button type="button" className="text-action" onClick={copyResponse}>
            {copyStatus === "Response copied" ? "Copied" : "Copy response"}
          </button>
          <span className="action-feedback" role="status" aria-live="polite">{copyStatus}</span>
          {response.model && <span className="answered-by">Answered by {response.model}</span>}
        </div>}
      </div>
    </article>
  );
}
