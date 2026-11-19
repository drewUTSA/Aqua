import React, { useId, useState } from "react";
import { initialRankFields, rankGroupsDraft, rankLabel, validRankNumber } from "./rankGroupsDraft.js";
import "../../styles/rank-groups.css";

function NameField({ name, label, value, onChange, placeholder }) {
  const hintId = useId();
  const invalid = value !== "" && !rankLabel(value);
  return <div className="rank-groups__name"><label>{label}<input type="text" name={name} value={value} placeholder={placeholder} required maxLength={64}
    autoComplete="off" aria-invalid={invalid || undefined} aria-describedby={invalid ? hintId : undefined} onChange={event => onChange(event.target.value)} /></label>
    {invalid && <small id={hintId}>Use words, numbers, spaces, hyphens or underscores. Start with a letter.</small>}
  </div>;
}

export default function RankGroupsComposer({ onApply }) {
  const [fields, setFields] = useState(initialRankFields);
  const numberHint = useId(), invalidNumber = fields.number !== "" && !validRankNumber(fields.number);
  const update = (key, value) => setFields(previous => ({ ...previous, [key]: value }));
  const draft = rankGroupsDraft(fields);
  return <details className="rank-groups">
    <summary>Rank groups</summary>
    <form className="rank-groups__form" aria-label="Rank groups" onSubmit={event => {
      event.preventDefault();
      if (draft) onApply(draft);
    }}>
      <p>Rank the groups present in a source you can access.</p>
      <div className="rank-groups__fields">
        <NameField name="source" label="Source" value={fields.source} placeholder="e.g. loans" onChange={value => update("source", value)} />
        <NameField name="group" label="Group by" value={fields.group} placeholder="e.g. branches" onChange={value => update("group", value)} />
        <label>Measure<select name="measure" value={fields.measure} onChange={event => update("measure", event.target.value)}>
          <option value="count">Count records</option><option value="total">Total a field</option></select></label>
        {fields.measure === "total" && <NameField name="field" label="Field to total" value={fields.field} placeholder="e.g. balance"
          onChange={value => update("field", value)} />}
        <label>Direction<select name="direction" value={fields.direction} onChange={event => update("direction", event.target.value)}>
          <option value="top">Highest first</option><option value="bottom">Lowest first</option></select></label>
        <div><label>Number<input name="number" type="number" inputMode="numeric" min="1" max="1000" step="1" required value={fields.number}
          aria-invalid={invalidNumber || undefined} aria-describedby={invalidNumber ? numberHint : undefined}
          onChange={event => update("number", event.target.value)} /></label>
          {invalidNumber && <small id={numberHint}>Enter a whole number from 1 to 1,000.</small>}</div>
        <label>Ties<select name="ties" value={fields.ties} onChange={event => update("ties", event.target.value)}>
          <option value="peers">Include ties at the cutoff</option><option value="fixed">Exactly this many groups</option>
          <option value="levels">This many distinct scores</option></select></label>
      </div>
      {draft && <p className="rank-groups__preview"><strong>Draft preview</strong> {draft}</p>}
      <button type="submit" disabled={!draft}>Use this draft</button>
    </form>
  </details>;
}
