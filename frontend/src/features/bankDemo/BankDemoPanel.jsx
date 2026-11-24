import React, { useId, useState } from "react";
import { useBankDemo } from "./useBankDemo.js";
import BankCalculator from "./BankCalculator.jsx";
import "./bank-demo.css";

function ReportPicker({ context, selected, reading, onSelect, onRead }) {
  const picker = useId(), evidence = useId(), startId = useId(), endId = useId();
  const [mode, setMode] = useState("snapshot");
  const [start, setStart] = useState(""), [end, setEnd] = useState("");
  function clearRead(set, value) {
    set(value);
    onSelect(selected);
  }
  function submit(event) {
    event.preventDefault();
    if (mode === "snapshot") { onRead(); return; }
    onRead({ source: mode === "dates" ? "fictional_snapshot" : "institution_record",
      period_start: mode === "dates" ? start || null : null, period_end: mode === "dates" ? end || null : null });
  }
  return <form onSubmit={submit} className="bank-demo__picker">
    <label htmlFor={evidence}>Evidence needed</label>
    <select id={evidence} value={mode} onChange={event => clearRead(setMode, event.target.value)} disabled={reading} data-bank-evidence>
      <option value="snapshot">Available fictional snapshot</option>
      <option value="dates">Fictional figures for specific dates</option>
      <option value="institution">Institution-approved record</option>
    </select>
    {mode === "dates" && <fieldset className="bank-demo__dates" disabled={reading}>
      <legend>Reporting period, inclusive</legend>
      <div><label htmlFor={startId}>Start date</label>
        <input id={startId} type="date" value={start} max={end || undefined} required onChange={e => clearRead(setStart, e.target.value)} /></div>
      <div><label htmlFor={endId}>End date</label>
        <input id={endId} type="date" value={end} min={start || undefined} required onChange={e => clearRead(setEnd, e.target.value)} /></div>
    </fieldset>}
    <label htmlFor={picker}>Choose an available fictional report</label>
    <select id={picker} value={selected} onChange={event => onSelect(event.target.value)} disabled={reading} data-bank-report-picker>
      <option value="">Choose a report</option>
      {context.reports.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select>
    <button type="submit" disabled={!selected || reading} data-bank-read>{reading ? "Reading report…" : mode === "snapshot" ? "Read fictional report" : "Check report availability"}</button>
  </form>;
}

function ReportLimitation({ limit }) {
  if (limit.reason === "institution_source_unavailable") {
    return <p role="status">This report uses fictional data. For an institution-approved figure or filing, request the approved record from your reporting team.</p>;
  }
  if (limit.reason === "period_required") return <p role="status">Enter both dates of the reporting period to check this report.</p>;
  return <p role="status">The requested period is unavailable. This report covers <time dateTime={limit.periodStart}>{limit.periodStart}</time> through <time dateTime={limit.periodEnd}>{limit.periodEnd}</time>.</p>;
}

export function BankDemoContent({ state, onSelect, onRead, onReload, onCalculate }) {
  const table = useId();
  const [calculatorVersion, setCalculatorVersion] = useState(0);
  function resetCalculator(callback, value) {
    setCalculatorVersion(version => version + 1);
    callback(value);
  }
  const context = state.context, report = state.result;
  const loading = ["idle", "loading"].includes(state.phase), reading = state.phase === "reading";
  return <section className="bank-demo-panel" aria-label="Fictional bank reports and calculator" data-bank-demo>
    <h3>Bank reports and calculator</h3>
    <p>No real bank is connected. Read fictional reports and their cited procedures, or calculate a USD illustration. This demo cannot approve or execute actions.</p>
    {loading && <div role="status" aria-live="polite"><p>Checking the available fictional reports…</p><div className="bank-demo__skeleton" aria-hidden="true" /></div>}
    {state.error && <p role="alert" className="bank-demo__error">{state.error}</p>}
    {!loading && !context && <button type="button" onClick={onReload} data-bank-reload>Check demo availability</button>}
    {context && <>
      <dl className="bank-demo__facts"><div><dt>Demonstration</dt><dd>{context.bankName}</dd></div>
        <div><dt>Server-configured demo scope</dt><dd>{context.persona} — fictional scope, not bank identity</dd></div>
        <div><dt>Snapshot</dt><dd><time dateTime={context.asOf}>{context.asOf}</time> · US · monetary amounts in USD</dd></div>
        <div><dt>Source version</dt><dd><span title={context.sourceRevision}>{context.sourceRevision.slice(0, 12)}</span></dd></div></dl>
      <p>{context.notice}</p>
      {state.phase === "empty" ? <p role="status">No fictional reports are assigned to this demo scope. Ask the operator to configure a demonstration scope; your app role does not grant bank access.</p>
        : <ReportPicker key={context.ownerId + context.sourceRevision} context={context} selected={state.selected}
            reading={reading} onSelect={value => resetCalculator(onSelect, value)} onRead={value => resetCalculator(onRead, value)} />}
    </>}
    {context && context.persona !== "none" && onCalculate && <BankCalculator key={context.ownerId + context.sourceRevision + calculatorVersion + (report?.reportId ?? "")}
      context={context} report={report} onCalculate={onCalculate} />}
    {reading && <p role="status">Reading the selected fictional report…</p>}
    {state.limitation && <ReportLimitation limit={state.limitation} />}
    {report && <article className="bank-demo__report" data-bank-report aria-labelledby={table}>
      <h4 id={table}>{report.title}</h4>
      <p><strong>Fictional · Partial period</strong> · <time dateTime={report.periodStart}>{report.periodStart}</time> through <time dateTime={report.periodEnd}>{report.periodEnd}</time> · monetary amounts in USD</p>
      <p>{report.definition}</p>
      <div className="bank-demo__table" tabIndex={0} role="region" aria-label="Fictional report figures, scroll if needed">
        <table><caption>Exact fictional aggregates for {report.title}</caption>
          <thead><tr>{report.columns.map(column => <th key={column.key} scope="col">{column.label}{column.unit !== "text" ? ` (${column.unit})` : ""}</th>)}</tr></thead>
          <tbody>{report.rows.map((row, index) => <tr key={index}>{row.map((cell, column) => <td key={report.columns[column].key}>{cell}</td>)}</tr>)}</tbody>
        </table>
      </div>
      <p>Values are shown exactly as supplied. This snapshot is not a complete month, live bank data or a forecast.</p>
      <ul>{report.caveats.map((text, index) => <li key={index}>{text}</li>)}</ul>
      <details className="bank-demo__procedure"><summary>Cited fictional procedure and human next steps</summary>
        <h5>{report.procedure.title}</h5><p>{report.procedure.text}</p>
        <p>Fictional procedure · {report.procedure.sourceId} · version {report.procedure.version}</p>
        <p>Procedure fingerprint: <span title={report.procedure.contentSha256}>{report.procedure.contentSha256.slice(0, 12)}</span></p>
        <p>Source: <span title={report.sourceRevision}>{report.sourceRevision.slice(0, 12)}</span> · as of {report.asOf}. This is demonstration material, not an approved bank policy.</p>
        <h5>Human next steps</h5><ol>{report.nextSteps.map(item => <li key={item.id}>{item.text}</li>)}</ol>
        <p>These are suggestions only. No approval has been recorded and no action can execute.</p>
      </details>
    </article>}
  </section>;
}

export default function BankDemoPanel({ auth, targetId, onClose }) {
  const bank = useBankDemo({ ownerId: auth.user?.id, csrfToken: auth.csrfToken, targetId, onClose, onAuthFailure: auth.refresh });
  return <BankDemoContent state={bank.state} onSelect={bank.select} onRead={bank.read} onReload={bank.load} onCalculate={bank.calculate} />;
}
