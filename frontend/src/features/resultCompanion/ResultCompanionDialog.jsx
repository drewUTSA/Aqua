import React, { useEffect, useId, useRef, useState } from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";
import GuidedQuestionFields from "../../components/workspace/GuidedQuestionFields.jsx";
import { guidedFieldValue, guidedQuestionMessage, prepareGuidedQuestion } from "../../services/guidedQuestion.js";
import { boundedCompanionQuestion } from "../../services/companionClient.js";
import { useResultCompanion } from "./useResultCompanion.js";
import { FOLLOWUPS, resultFollowupFields } from "./followup.js";
import "../../styles/companion-tools.css";
import "./result-companion.css";

function Witnesses({ extreme, field }) {
  return <ul className="result-companion__witnesses" aria-label="Saved row references">{extreme.witness_rows.map(index =>
    <li key={index}>Saved row {index + 1}, field {field.index + 1} ({field.key}): <code>{extreme.value}</code></li>)}</ul>;
}

export function ResultCompanionFacts({ brief }) {
  const { counts, field, numeric } = brief;
  return <section className="result-companion__facts" data-result-facts aria-label="Saved field facts">
    <h3>What this result shows</h3>
    {counts.returned_rows === 0 ? <p>This query returned no rows. This does not establish that the underlying activity never exists.</p>
      : <p>Among the <strong>{counts.returned_rows} returned {counts.returned_rows === 1 ? "row" : "rows"}</strong>, <strong>{counts.missing_values}</strong> saved {counts.missing_values === 1 ? "value is" : "values are"} missing in this field. {counts.non_missing_values} {counts.non_missing_values === 1 ? "has" : "have"} a value.</p>}
    <p>Field: <strong>{field.label}</strong>. Unit unspecified.</p>
    {brief.status === "limited" && <p role="status">This older saved result has limited precision and provenance information. Numerical comparisons are unavailable; its original table is unchanged.</p>}
    {numeric ? <div className="result-companion__range">
      {(counts.returned_rows === 1 ? [["Saved value (one returned row)", numeric.minimum]] : [["Lowest saved value among returned rows", numeric.minimum], ["Highest saved value among returned rows", numeric.maximum]]).map(([label, value]) =>
        <section key={label}><h4>{label}</h4><p className="result-companion__value"><code>{value.value}</code></p>
          <p>{value.ties} returned {value.ties === 1 ? "row has" : "rows have"} this value. {value.ties > value.witness_rows.length ? "Up to three saved row references are shown." : ""}</p>
          <Witnesses extreme={value} field={field} /></section>)}
    </div> : brief.status === "ready" && counts.non_missing_values > 0 && <p>No numerical range is provided for this {field.kind === "mixed" ? "mixed-type" : field.kind} field.</p>}
    <p className="result-companion__limit">These facts describe the saved returned rows, not all matching records, people or accounts. Row references use the original saved order, before table sorting or paging.</p>
    <h3>What to check before using it</h3>
    <ul>{brief.checks.map(check => <li key={check.id}>{check.text}</li>)}</ul>
    <details><summary>Saved source and limits</summary><dl>
      <div><dt>Source</dt><dd>{brief.source.id ? <span title={brief.source.id}>{brief.source.id.slice(0, 12)}</span> : "Not recorded"}</dd></div>
      <div><dt>Answer generated</dt><dd>{brief.source.generated_at ? <time dateTime={brief.source.generated_at}>{brief.source.generated_at}</time> : "Not recorded"}</dd></div>
      <div><dt>Source freshness</dt><dd>Unknown; generation time is not source freshness.</dd></div>
      <div><dt>Filters and aggregation</dt><dd>Unspecified</dd></div>
      <div><dt>Returned list</dt><dd>{brief.scope.truncated === true ? "Truncated" : brief.scope.truncated === false ? "Not marked truncated; underlying scope still needs review" : "Truncation not recorded"}</dd></div>
    </dl></details>
  </section>;
}

export function ResultCompanionContent({ binding, state, onColumn, onRetry, onIntent, guide, onField, onPrepare, onDraft, onApply, fieldRefs, canApply = true }) {
  const selectId = useId(), questionId = useId(), draftId = useId();
  const brief = state.reply?.brief, guiding = brief && guide?.ticket === state.ticket;
  return <div className="result-companion" data-result-companion>
    <p>These checks use your saved answer. They do not rerun its query, explain business causes or perform actions.</p>
    <section aria-labelledby={questionId}><h3 id={questionId}>Original question</h3><p className="result-companion__question">{brief?.question || binding.question || "Read the saved-field check to see its original question."}</p></section>
    <label htmlFor={selectId}>Returned field to inspect</label>
    <select id={selectId} data-result-column value={state.columnIndex} onChange={event => onColumn(Number(event.target.value))}>
      {binding.table.columns.map((column, index) => <option key={column.key} value={index}>{column.label || column.key}</option>)}
    </select>
    {["idle", "loading"].includes(state.phase) && <p role="status">Reading this saved field…</p>}
    {state.error && <div role="alert"><p>{state.error}</p><button type="button" data-result-retry onClick={onRetry}>Retry saved-field check</button></div>}
    {brief && <><ResultCompanionFacts brief={brief} />
      <section className="result-companion__followup" aria-label="Prepare a follow-up">
        <h3>Prepare a better question</h3>
        <p>Choose a starting point, then supply the details you know. A new question is not anchored to this saved answer’s exact SQL, filters or period.</p>
        <div className="result-companion__intents">{brief.followup_intents.map(intent => <button key={intent} type="button" data-result-intent={intent} onClick={() => onIntent(intent)}>{FOLLOWUPS[intent]}</button>)}</div>
        {guiding && <>
          <GuidedQuestionFields fields={guide.fields} error={guide.error} onField={onField} onPrepare={onPrepare} fieldRefs={fieldRefs} />
          {!guide.fields.measure && <p>Add the measure you want Aqua to return. No suggested value was truncated to fit.</p>}
          <label htmlFor={draftId}>Follow-up draft for review</label>
          <textarea id={draftId} data-result-draft value={guide.draft} maxLength={2000} rows={5} onChange={event => onDraft(event.target.value)} />
          {guide.error?.field === "draft" && <p role="alert">{guide.error.message}</p>}
          <p>{guide.dirty ? "Prepare the draft to review the current guide fields." : guide.edited ? "Your edited draft is what will be applied. Prepare again to replace it with the guide fields." : "Review the draft before applying. Unspecified details remain explicit."} Your composer will be replaced only after Apply. Nothing is sent.</p>
          {guide.conflict && <p role="alert">Your composer or selected result changed. Its text was preserved. Close this panel and review the current draft.</p>}
          {!canApply && <p>Applying a follow-up requires current data access and an active, unarchived chat.</p>}
          <button type="button" data-result-apply disabled={!canApply || guide.dirty || !!guide.error || !guide.draft.trim()} onClick={onApply}>Apply to composer draft</button>
        </>}
      </section></>}
  </div>;
}

export default function ResultCompanionDialog({ binding, csrfToken, historyContext, draft, onApply, onClose, onAuthFailure, canApply }) {
  const result = useResultCompanion({ binding, csrfToken, historyContext, onClose, onAuthFailure });
  const [guide, setGuide] = useState(null), closeRef = useRef(null), fieldRefs = useRef({}), originalDraft = useRef(draft);
  useEffect(() => { setGuide(null); }, [result.state.ticket, binding.token]);
  const currentGuide = () => result.current() && result.state.reply && guide?.ticket === result.state.ticket;
  const chooseIntent = intent => {
    if (!result.current() || !result.state.reply?.brief.followup_intents.includes(intent)) return;
    const fields = resultFollowupFields(intent, result.state.reply.brief.field.label);
    if (fields) setGuide({ fields, ticket: result.state.ticket, draft: "", dirty: true, edited: false, error: null, conflict: false });
  };
  const onField = (field, value) => {
    if (!currentGuide()) return;
    try { guidedFieldValue(field, value); setGuide(current => ({ ...current, fields: { ...current.fields, [field]: value }, dirty: true, error: null, conflict: false })); }
    catch (error) { setGuide(current => ({ ...current, dirty: true, error: { field, message: guidedQuestionMessage(error) } })); }
  };
  const onPrepare = () => {
    if (!currentGuide()) return;
    try { const prepared = prepareGuidedQuestion(guide.fields); setGuide(current => ({ ...current, draft: prepared.question, dirty: false, edited: false, error: null, conflict: false })); }
    catch (error) { setGuide(current => ({ ...current, dirty: true, error: { field: error.field || "measure", message: guidedQuestionMessage(error) } })); fieldRefs.current[error.field || "measure"]?.focus(); }
  };
  const apply = () => {
    if (!canApply || !currentGuide() || guide.dirty || guide.error || !guide.draft.trim()) return;
    try { boundedCompanionQuestion(guide.draft); } catch { return; }
    if (onApply(guide.draft, { token: binding.token, draft: originalDraft.current })) onClose();
    else setGuide(current => ({ ...current, conflict: true }));
  };
  return <PreferenceDialog title="Understand this result" className="result-companion-dialog companion-tools-dialog" onClose={onClose} initialFocusRef={closeRef}>
    <ResultCompanionContent binding={binding} state={result.state} onColumn={result.select} onRetry={result.retry} onIntent={chooseIntent}
      guide={guide} onField={onField} onPrepare={onPrepare} fieldRefs={fieldRefs} onApply={apply}
      canApply={canApply} onDraft={value => { if (!currentGuide()) return;
        let error = null;
        try { boundedCompanionQuestion(value); } catch { if (value) error = { field: "draft", message: "Use plain text with no more than 2,000 characters and 8,000 UTF-8 bytes." }; }
        setGuide(current => ({ ...current, draft: value, dirty: false, edited: true, error, conflict: false })); }} />
    <div className="settings-dialog-actions"><button type="button" ref={closeRef} data-close-result-companion onClick={onClose}>Close result companion</button></div>
  </PreferenceDialog>;
}
