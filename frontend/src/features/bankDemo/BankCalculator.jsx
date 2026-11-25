import React, { useEffect, useId, useRef, useState } from "react";
import { choices, fieldsFromReport, inputPattern, labels, operations, reportValues, rowLabel } from "./calculator.js";

const errors = {
  finance_positive_amount: "The baseline, principal or outflow must be greater than zero. Check the amount you entered.",
  finance_term: "Use 1–600 whole months or 1–18,300 elapsed days.",
  finance_rate: "Enter an annual percentage from 0 to 100, using up to six decimal places.",
  finance_amount: "Enter full USD amounts with up to two decimal places, up to one trillion dollars.",
  finance_payment_below_cent: "These terms do not produce a payment of at least one cent.",
  finance_rounding_prevents_amortization: "The rounded payments would not pay down the principal. Check the terms.",
};

function Terms({ values }) {
  return <dl className="bank-demo__facts">{Object.entries(values).filter(([name]) => name !== "currency")
    .map(([name, value]) => <div key={name}><dt>{labels[name]}</dt><dd>{value}</dd></div>)}</dl>;
}

export default function BankCalculator({ context, report, onCalculate, cash }) {
  const prefix = useId(), reviewHeading = useRef(null), request = useRef(null);
  const [fromQuestion, setFromQuestion] = useState(Boolean(cash && !cash.manual));
  const [operation, setOperation] = useState(cash ? "liquidity_coverage" : ""), [useReport, setUseReport] = useState(false);
  const [row, setRow] = useState(""), [field, setField] = useState(""), [values, setValues] = useState({});
  const [draft, setDraft] = useState(null), [result, setResult] = useState(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => { if (draft) reviewHeading.current?.focus(); }, [draft]);
  const fields = operations[operation]?.[1] ?? [], sources = operation ? fieldsFromReport(operation, report) : [];
  const filled = useReport && row !== "" && field ? reportValues(report, Number(row), field) : {};
  const quoted = fromQuestion ? [...new Map(cash.amounts.map(a => [a.value, a])).values()] : [];
  function quotedOptions(name) {
    const otherField = name === "available_liquidity_usd" ? "projected_outflows_usd" : "available_liquidity_usd";
    return quoted.filter(a => quoted.length === 1 || a.value !== values[otherField]);
  }
  function resetAnswer() {
    request.current?.abort(); request.current = null;
    setDraft(null); setResult(null); setBusy(false); setError("");
  }
  function resetSource() {
    resetAnswer(); setRow(""); setField(""); setValues({});
  }
  function review(event) {
    event.preventDefault();
    if (!fields.length || (useReport && (row === "" || !field))) return;
    if (fromQuestion && (!["available_liquidity_usd", "projected_outflows_usd"].every(name => quotedOptions(name).some(a => a.value === values[name]))
        || values.period !== cash.period || Number(values.projected_outflows_usd) === 0)) {
      resetAnswer(); setError("Choose both amounts from the question. Projected outflows must be positive."); return;
    }
    resetAnswer();
    const params = Object.fromEntries(fields.filter(name => !Object.hasOwn(filled, name)).map(name => [name, values[name]]));
    const reference = useReport ? {report_id: report.reportId, row: Number(row), field, period_start: report.periodStart, period_end: report.periodEnd} : null;
    const rowLabels = useReport ? Object.fromEntries(report.columns.flatMap((c, i) => c.unit === "text" ? [[c.label, report.rows[Number(row)][i]]] : [])) : null;
    setDraft({ schemaVersion: 1, confirmed: true, currency: "USD", operation, expected_source_revision: context.sourceRevision,
      parameters: params, ...(reference ? {report: reference, rowLabels, reportTitle: report.title} : {}),
      confirmedInputs: {...params, ...filled, currency: "USD"} });
  }
  async function confirm() {
    if (!draft || request.current) return;
    const current = new AbortController();
    request.current = current; setBusy(true); setError("");
    try {
      const answer = await onCalculate(draft, current.signal);
      if (request.current !== current || current.signal.aborted) return;
      if (answer.unavailable) setError(errors[answer.unavailable] || "These terms cannot produce this illustration. Review the supplied values.");
      else setResult(answer);
    } catch (e) {
      if (request.current !== current || current.signal.aborted) return;
      setError(e?.status === 409 ? "The source changed. Read the report again before calculating."
        : e?.status === 403 ? "The current role cannot use this source. Reload the available reports."
        : "Aqua could not verify the calculation. Check your session and the supplied terms.");
    } finally {
      if (request.current === current) { request.current = null; setBusy(false); }
    }
  }
  return <details className="bank-demo__procedure bank-calculator" data-bank-calculator open={cash ? true : undefined}>
    <summary>Banking calculator</summary>
    <p>Review the amounts and assumptions before calculating a fictional USD illustration.</p>
    {fromQuestion && <><p>Your question</p><blockquote>{cash.question}</blockquote><p>Choose the available cash and projected outflows from your question. Select the shared period only if both figures cover that same {cash.period}.</p></>}
    {!fromQuestion && !report && context.reports.some(r => ["consumer_pipeline_summary", "commercial_exposure_summary", "reconciliation_summary"].includes(r.id)) &&
      <p>To use figures from a lending or reconciliation report, read that report above.</p>}
    <form onSubmit={review} className="bank-calculator__form">
      <label htmlFor={prefix + "operation"}>Calculation</label>
      <select id={prefix + "operation"} data-calc-operation value={operation} required onChange={e => { resetSource(); setFromQuestion(false); setUseReport(false); setOperation(e.target.value); }}>
        <option value="">Choose a calculation</option>{Object.entries(operations).map(([key, [label]]) => <option key={key} value={key}>{label}</option>)}
      </select>
      {!!sources.length && <><label htmlFor={prefix + "source"}>Amount source</label>
        <select id={prefix + "source"} value={useReport ? "report" : "manual"} onChange={e => { resetSource(); setUseReport(e.target.value === "report"); }}>
          <option value="manual">Amounts I supply</option><option value="report">Current fictional report</option>
        </select></>}
      {useReport && !!sources.length && <>
        <p>{report.title} · {report.periodStart} through {report.periodEnd}</p>
        <label htmlFor={prefix + "row"}>Report row</label>
        <select id={prefix + "row"} value={row} required onChange={e => { resetAnswer(); setValues({}); setRow(e.target.value); }}>
          <option value="">Choose a row</option>{report.rows.map((_, i) => <option key={i} value={i}>{rowLabel(report, i)}</option>)}
        </select>
        <label htmlFor={prefix + "field"}>Figures to use</label>
        <select id={prefix + "field"} value={field} required onChange={e => { resetAnswer(); setValues({}); setField(e.target.value); }}>
          <option value="">Choose the reported figures</option>{sources.map(([key, label]) => <option value={key} key={key}>{label}</option>)}
        </select>
      </>}
      {!!fields.length && <fieldset><legend>Illustration terms</legend>
        <p>Enter full dollar amounts without commas. Use up to two decimal places for money.</p>
        {fields.map(name => <div key={name}><label htmlFor={prefix + name}>{labels[name]}</label>
          {Object.hasOwn(filled, name) ? <input id={prefix + name} value={filled[name]} readOnly />
            : fromQuestion && name.endsWith("_usd") ? <select id={prefix + name} data-quoted-cash={name} value={values[name] ?? ""} required onChange={e => { resetAnswer(); setValues({...values, [name]: e.target.value}); }}>
              <option value="">Choose an amount from your question</option>
              {quotedOptions(name).map(a => <option key={a.value} value={a.value}>{a.literal} USD</option>)}
            </select> : choices[name] ? <select id={prefix + name} value={values[name] ?? ""} required onChange={e => { resetAnswer(); setValues({...values, [name]: e.target.value}); }}>
              <option value="">Choose {labels[name].toLowerCase()}</option>{(useReport && operation === "reconciliation" && name === "period" ? ["statement"] : fromQuestion && name === "period" ? [cash.period] : choices[name]).map(x => <option key={x}>{x}</option>)}
            </select> : <input id={prefix + name} data-calc-input={name} value={values[name] ?? ""} required inputMode={["term_months", "elapsed_days"].includes(name) ? "numeric" : "decimal"}
              pattern={inputPattern(name)} maxLength={18} onChange={e => { resetAnswer(); setValues({...values, [name]: e.target.value}); }} />}
        </div>)}
      </fieldset>}
      {!!fields.length && <button type="submit" data-calc-review>Review illustration</button>}
    </form>
    {draft && <section aria-label="Review illustration" className="bank-calculator__review">
      <h4 tabIndex={-1} ref={reviewHeading}>Review your illustration</h4>
      <p>{operations[operation][0]} · {draft.report ? report.title + " · " + rowLabel(report, draft.report.row) + " · " + sources.find(([key]) => key === field)?.[1] : "Employee-supplied figures"}</p>
      {draft.report && <p>{draft.report.period_start} through {draft.report.period_end}</p>}
      <Terms values={draft.confirmedInputs} />
      {!result && <button type="button" data-calc-confirm onClick={confirm} disabled={busy}>{busy ? "Calculating…" : "Confirm and calculate"}</button>}
    </section>}
    {error && <p role="alert" className="bank-demo__error">{error}</p>}
    {result && <section aria-label="Illustration result" role="status" className="bank-calculator__result">
      <h4>Illustration result</h4><p>{result.explanation}</p>
      {result.operation === "liquidity_coverage" && <p>Available cash less projected outflows is {result.result.surplus_or_shortfall_usd} USD.</p>}
      {result.operation === "simple_interest_actual_days" && <p>Principal plus interest is {result.result.principal_plus_interest_usd} USD.</p>}
      <details><summary>Formula and assumptions</summary><ul>{result.assumptions.map(line => <li key={line}>{line}</li>)}</ul></details>
    </section>}
  </details>;
}
