import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import PlotlyChart from "../data/PlotlyChart.jsx";
import FinancialTable from "../data/FinancialTable.jsx";
import ResultMetadata from "../data/ResultMetadata.jsx";

const reasons = { precision_limit: "Exact values are preserved in the table. Chart approximation is disabled.", point_limit: "This result exceeds the chart point limit. Use the table and export.",
  invalid_axis: "These axes cannot be charted reliably. Use the result table.", ambiguous_units: "The measures have unspecified or incompatible units. Use the result table.",
  no_rows: "No rows matched this request.", scalar_result: "This result contains a single value.", unsupported_shape: "This result is available as a table." };

export default function VisualPane({ visuals, shell, owner, suspended, hidden, canExpand }) {
  const { result, view, change, selected } = visuals;
  const scroll = useRef(null), positions = useRef(new Map());
  const [activated, setActivated] = useState(!hidden);
  const [contextChanged, setContextChanged] = useState(false);
  const previousContext = useRef(null);
  useEffect(() => { if (!hidden) setActivated(true); }, [hidden]);
  const compatibility = result?.descriptor?.compatibility_key;
  useEffect(() => { if (!compatibility) return; setContextChanged(previousContext.current !== null && previousContext.current !== compatibility);
    previousContext.current = compatibility; }, [compatibility]);
  useLayoutEffect(() => { if (!hidden && !suspended && scroll.current) scroll.current.scrollTop = positions.current.get(selected?.id) || 0; }, [selected?.id, view.mode, hidden, suspended]);
  const failure = view.failed || (view.pending && visuals.chat.uncertain);
  const retry = () => { if (!view.failed) { visuals.chat.checkSaved?.(); return; }
    const failed = visuals.chat.messages.find((message) => message.id === view.failed);
    if (failed?.response?.error?.retryable) visuals.chat.retry(view.failed);
    else { const question = visuals.chat.messages.find((message) => message.id === failed?.replyTo)?.content; if (question) visuals.chat.submit(question); } };
  return <aside className="visual-pane" aria-label="Result visuals" hidden={hidden} inert={hidden || undefined}>
    <header className="visual-pane__header"><h2>Visuals</h2><div>
      {canExpand && <button type="button" onClick={() => change((previous) => ({ ...previous, expanded: !previous.expanded }))} aria-pressed={view.expanded}>{view.expanded ? "Restore split" : "Expand visuals"}</button>}
      <button type="button" onClick={visuals.close}>Close visuals</button></div></header>
    {result && <div className="visual-pane__tabs" role="group" aria-label="Result view">
      <button type="button" aria-pressed={view.mode === "chart"} disabled={!result.descriptor} onClick={() => change((previous) => ({ ...previous, mode: "chart" }))}>Chart</button>
      <button type="button" aria-pressed={view.mode === "table"} onClick={() => change((previous) => ({ ...previous, mode: "table" }))}>Table</button></div>}
    <div className="visual-pane__scroll" ref={scroll} onScroll={(event) => { if (selected && !hidden && !suspended) { positions.current.set(selected.id, event.currentTarget.scrollTop);
      if (positions.current.size > 200) positions.current.delete(positions.current.keys().next().value); } }}>
      {view.pending?.intent !== "text" && view.pending && <p role="status">Updating visual{result ? ". Showing the previous result until the update is ready." : "…"}</p>}
      {failure && <p role="status">Couldn’t update the visual.{result ? " Showing the previous result." : " Check the conversation for details."}
        <button type="button" disabled={visuals.chat.pending} onClick={retry}>Retry visual update</button></p>}
      {result && <><p className="visual-pane__question">{result.question}</p><ResultMetadata response={result.response} />
        {result.response.presentationError && <p role="status">{result.response.presentationError}</p>}
        {contextChanged && <p role="status">Chart context changed. Zoom was reset for the new query, period, axes or units.</p>}
        {!result.descriptor && <p>{reasons[result.reason] || "Use the result table for this response."}</p>}
        {result.descriptor && <p className="visual-pane__context">{result.descriptor.x.kind === "datetime" ? "Time axis: UTC. " : result.descriptor.x.kind === "date" ? "Calendar dates; no timezone conversion. " : result.descriptor.x.kind === "calendar" ? "Calendar periods in order; absent periods are not filled or spaced as elapsed time. " : "Categories in result order. "}
          Units: {result.descriptor.series.map((series) => `${series.label}: ${series.unit || "unspecified"}`).join("; ")}. Missing values remain gaps. All {result.descriptor.input_rows} returned rows; no additional chart aggregation or sampling.</p>}
        {result.descriptor && activated && !suspended && <div hidden={view.mode !== "chart"}><PlotlyChart key={owner} descriptor={result.descriptor} table={result.table} theme={shell}
          onTableView={() => change((previous) => ({ ...previous, mode: "table" }))} /></div>}
        {(!result.descriptor || view.mode === "table" || suspended) && <FinancialTable table={result.table} />}
      </>}
      {!result && !view.pending && <p>No selected visual. Choose a result in this conversation.</p>}
    </div>
  </aside>;
}
