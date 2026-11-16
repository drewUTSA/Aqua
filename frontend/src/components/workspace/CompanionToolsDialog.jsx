import React, { useId, useRef, useState } from "react";
import PreferenceDialog from "../../settings/PreferenceDialog.jsx";
import { useCompanionTools } from "../../hooks/useCompanionTools.js";
import { prepareCompanionDraft } from "../../services/aquaClient.js";
import { GUIDED_FIELDS, GUIDED_FIELD_CHARACTERS, emptyGuidedQuestion, guidedFieldValue, guidedQuestionMessage, prepareGuidedQuestion } from "../../services/guidedQuestion.js";
import "../../styles/companion-tools.css";

export function GuidedQuestionFields({ fields, error, onField, onPrepare, fieldRefs }) {
  const prefix = useId();
  return <fieldset className="companion-tools__guide"><legend>Build a question</legend>
    <p>Use terms you know. Aqua has not checked these fields against your dataset. Review unspecified details before sending; you may need a more specific question.</p>
    {GUIDED_FIELDS.map(({ id, label }) => <div className="companion-tools__field" key={id}>
      <label htmlFor={`${prefix}-${id}`}>{label}</label>
      <input id={`${prefix}-${id}`} data-companion-guide-field={id} type="text" value={fields[id]} maxLength={GUIDED_FIELD_CHARACTERS} required={id === "measure"}
        autoComplete="off" ref={(node) => { if (fieldRefs) fieldRefs.current[id] = node; }}
        aria-invalid={error?.field === id || undefined} aria-describedby={error?.field === id ? `${prefix}-${id}-error` : undefined}
        onChange={(event) => onField(id, event.target.value)} />
      {error?.field === id && <p id={`${prefix}-${id}-error`} role="alert" className="companion-tools__guide-error">{error.message}</p>}
    </div>)}
    <button type="button" data-companion-guide-prepare onClick={onPrepare}>Prepare draft for review</button>
  </fieldset>;
}

export function CompanionToolsContent({ state, mode, question, canQuery, onMode, onQuestion, onRead, onApply, onReload,
  guide = { active: false }, onGuide, onGuideField, onPrepareGuide, guideRefs }) {
  const label = useId(), description = useId();
  const ready = Boolean(state.menu), queryAllowed = canQuery && state.menu?.capabilities.some((tool) => tool.id === "authorized_question");
  return <>
    <p id={description}>Help reads reviewed Aqua guidance. Ask data only copies text to your composer; you decide whether to send it.</p>
    {state.phase === "loading" && <p role="status">Checking available tools…</p>}
    {state.error && <p role="alert" data-companion-error>{state.error}</p>}
    {!ready && ["error", "unavailable"].includes(state.phase) && <button type="button" onClick={onReload}>Check availability</button>}
    {ready && <>
      <fieldset className="companion-tools__choice"><legend>Choose a tool</legend>
        <button type="button" data-companion-mode="help" aria-pressed={mode === "help"} onClick={() => onMode("help")}>Help with Aqua</button>
        <button type="button" data-companion-mode="data" aria-pressed={mode === "data"} disabled={!queryAllowed} onClick={() => onMode("data")}>Ask data</button>
      </fieldset>
      {!queryAllowed && <p data-companion-denied>Ask data requires current dataset access. Reviewed help is still available.</p>}
      <form onSubmit={(event) => { event.preventDefault(); if (mode === "help") onRead(); }}>
        {mode === "data" && <>
          <fieldset className="companion-tools__choice"><legend>Prepare your question</legend>
            <button type="button" data-companion-guide-mode="free" aria-pressed={!guide.active} onClick={() => onGuide(false)}>Write freely</button>
            <button type="button" data-companion-guide-mode="guided" aria-pressed={guide.active} disabled={!queryAllowed} onClick={() => onGuide(true)}>Guide me</button>
          </fieldset>
          {guide.active && <GuidedQuestionFields fields={guide.fields} error={guide.error} onField={onGuideField} onPrepare={onPrepareGuide} fieldRefs={guideRefs} />}
          {guide.active && <p role="status" data-companion-guide-status>{guide.dirty ? "Prepare a draft to review these answers, or choose Write freely."
            : guide.review === "edited" ? "Your edited draft below is what will be applied. Prepare again to replace it with the guide answers."
              : "Draft prepared below. Review or edit it before applying."}</p>}
        </>}
        <label htmlFor={label}>{mode === "help" ? "Question about Aqua" : "Data-question draft"}</label>
        <textarea id={label} data-companion-question value={question} maxLength={2000} rows={4} aria-describedby={description}
          autoComplete="off" onChange={(event) => onQuestion(event.target.value)} />
        {mode === "help" ? <button type="submit" data-companion-read disabled={!question.trim() || state.phase === "reading"}>Read help</button>
          : <><p>The current composer draft will be replaced. Nothing is sent.</p><button type="button" data-companion-apply
            disabled={!queryAllowed || !question.trim() || guide.active && (guide.dirty || Boolean(guide.error))} onClick={onApply}>Apply to composer draft</button></>}
      </form>
      {state.phase === "reading" && <p role="status">Looking in reviewed Aqua help…</p>}
      {state.answer && <section data-companion-answer data-method={state.answer.method} aria-live="polite">
        <h3>{state.answer.status === "abstained" ? "No clear guide found" : "Reviewed help lookup"}</h3>
        <p>No model or data query was used.</p><p data-companion-message>{state.answer.message}</p>
        {state.answer.citations.length > 0 && <><h4>Reviewed sources</h4><ul>{state.answer.citations.map((source) => <li key={source.id}>
          <strong>{source.title}</strong><span>Source: {source.id}</span><span title={source.revision}>Version: {source.revision.slice(0, 12)}</span>
        </li>)}</ul></>}
      </section>}
    </>}
  </>;
}

export default function CompanionToolsDialog({ auth, targetId, draft, onApply, onClose }) {
  const [question, setQuestion] = useState(""), [mode, setMode] = useState("help"), closeRef = useRef(null), originalDraft = useRef(draft);
  const [guide, setGuide] = useState(() => ({ active: false, fields: emptyGuidedQuestion(), dirty: true, error: null, review: "" })), guideRefs = useRef({});
  const tools = useCompanionTools({ ownerId: auth.user?.id, csrfToken: auth.csrfToken, targetId, onClose, onAuthFailure: auth.refresh });
  const changeQuestion = (value) => { tools.edit(); setQuestion(value); setGuide((current) => ({ ...current, dirty: false, error: null, review: "edited" })); };
  const changeMode = (next) => { tools.edit(); setMode(next); };
  const changeGuide = (active) => { tools.edit(); setGuide((current) => ({ ...current, active, dirty: active, error: null, review: "" })); };
  const changeGuideField = (field, value) => {
    tools.edit();
    try { guidedFieldValue(field, value); setGuide((current) => ({ ...current, fields: { ...current.fields, [field]: value }, dirty: true, error: null, review: "" })); }
    catch (error) { setGuide((current) => ({ ...current, dirty: true, error: { field, message: guidedQuestionMessage(error) } })); }
  };
  const prepareGuide = () => {
    tools.edit();
    try { const prepared = prepareGuidedQuestion(guide.fields); setQuestion(prepared.question); setGuide((current) => ({ ...current, dirty: false, error: null, review: "prepared" })); }
    catch (error) { setGuide((current) => ({ ...current, dirty: true, error: { field: error.field || "measure", message: guidedQuestionMessage(error) } })); guideRefs.current[error.field || "measure"]?.focus(); }
  };
  const apply = () => {
    if (!tools.current() || !auth.canQuery || guide.active && (guide.dirty || guide.error)) return;
    try {
      const value = prepareCompanionDraft(question, tools.state.menu);
      if (onApply(value, { targetId, draft: originalDraft.current })) onClose(); else tools.conflict();
    } catch { tools.conflict(); }
  };
  return <PreferenceDialog title="Aqua tools" onClose={onClose} className="companion-tools-dialog" initialFocusRef={closeRef}>
    <CompanionToolsContent state={tools.state} mode={mode} question={question} canQuery={auth.canQuery}
      onMode={changeMode} onQuestion={changeQuestion} onRead={() => tools.ask(question)} onApply={apply} onReload={tools.load}
      guide={guide} onGuide={changeGuide} onGuideField={changeGuideField} onPrepareGuide={prepareGuide} guideRefs={guideRefs} />
    <div className="settings-dialog-actions"><button type="button" ref={closeRef} data-close-companion onClick={onClose}>Close Aqua tools</button></div>
  </PreferenceDialog>;
}
