import React, { useId, useLayoutEffect, useRef, useState } from "react";
import { initialRankFields, rankGroupsDraft, rankLabel, validRankNumber } from "./rankGroupsDraft.js";
import "../../styles/rank-groups.css";

function NameField({ name, label, value, onChange, placeholder, inputRef, description }) {
  const hintId = useId();
  const invalid = value !== "" && !rankLabel(value);
  return <div className="rank-groups__name"><label>{label}<input ref={inputRef} type="text" name={name} value={value} placeholder={placeholder} required maxLength={64}
    autoComplete="off" aria-invalid={invalid || undefined} aria-describedby={[invalid && hintId, description].filter(Boolean).join(" ") || undefined} onChange={event => onChange(event.target.value)} /></label>
    {invalid && <small id={hintId}>Use words, numbers, spaces, hyphens or underscores. Start with a letter.</small>}
  </div>;
}

export default function RankGroupsComposer({ onApply, onBack, original, reveal = false }) {
  const [fields, setFields] = useState(initialRankFields);
  const [copied, setCopied] = useState(false);
  const details = useRef(null), source = useRef(null), ties = useRef(null);
  useLayoutEffect(() => {
    details.current.open = false;
    setFields(initialRankFields);
    setCopied(false);
  }, [original]);
  useLayoutEffect(() => {
    if (reveal) {
      if (reveal.status === "complete") {
        setFields(reveal.fields || { source: "", group: "", measure: "", field: "", direction: "", number: "", ties: "" });
        setCopied(Boolean(reveal.fields));
      }
      details.current.open = true;
      (reveal.fields ? ties : source).current.focus();
    }
  }, [reveal]);
  const nameHint = useId(), numberHint = useId(), invalidNumber = fields.number !== "" && !validRankNumber(fields.number);
  const update = (key, value) => setFields(previous => ({ ...previous, [key]: value }));
  const draft = rankGroupsDraft(fields);
  return <details ref={details} className="rank-groups" onToggle={event => {
    if (original && event.currentTarget.open) source.current?.focus();
  }}>
    <summary>Rank groups</summary>
    <form className="rank-groups__form" aria-label="Rank groups" onSubmit={event => {
      event.preventDefault();
      if (draft) onApply(draft);
    }}>
      <p>{original ? "Choose ranking fields for a new draft. Your original question stays in Unsent drafts for this visit."
        : "Rank the groups present in a source you can access."} <span id={nameHint}>{copied
          ? "Fields were copied from your saved result. Review them and choose how to handle ties."
          : "Choose a source and grouping field you can access. A supported saved ranking can fill these in for you."}</span></p>
      <div className="rank-groups__fields">
        <NameField inputRef={source} name="source" label="Source" value={fields.source} placeholder="e.g. loans" description={nameHint} onChange={value => update("source", value)} />
        <NameField name="group" label="Group by" value={fields.group} placeholder="e.g. branches" description={nameHint} onChange={value => update("group", value)} />
        <label>Measure<select name="measure" value={fields.measure} onChange={event => update("measure", event.target.value)}>
          {!fields.measure && <option value="" disabled>Choose a measure</option>}
          <option value="count">Count records</option><option value="total">Total a field</option></select></label>
        {fields.measure === "total" && <NameField name="field" label="Field to total" value={fields.field} placeholder="e.g. balance"
          onChange={value => update("field", value)} />}
        <label>Direction<select name="direction" value={fields.direction} onChange={event => update("direction", event.target.value)}>
          {!fields.direction && <option value="" disabled>Choose a direction</option>}
          <option value="top">Highest first</option><option value="bottom">Lowest first</option></select></label>
        <div><label>Number<input name="number" type="number" inputMode="numeric" min="1" max="1000" step="1" required value={fields.number}
          aria-invalid={invalidNumber || undefined} aria-describedby={invalidNumber ? numberHint : undefined}
          onChange={event => update("number", event.target.value)} /></label>
          {invalidNumber && <small id={numberHint}>Enter a whole number from 1 to 1,000.</small>}</div>
        <label>Ties<select name="ties" ref={ties} value={fields.ties} aria-describedby={copied ? nameHint : undefined} onChange={event => update("ties", event.target.value)}>
          {!fields.ties && <option value="" disabled>Choose a tie rule</option>}
          <option value="peers">Include ties at the cutoff</option><option value="fixed">Exactly this many groups</option>
          <option value="levels">This many distinct scores</option></select></label>
      </div>
      {draft && <p className="rank-groups__preview"><strong>Draft preview</strong> {draft}</p>}
      <div className="rank-groups__actions"><button type="submit" disabled={!draft}>{original ? "Use in a new draft" : "Use this draft"}</button>
        {original && <button type="button" onClick={() => { details.current.open = false; onBack(); }}>Back to my question</button>}
      </div>
    </form>
  </details>;
}
