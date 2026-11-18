import React, { useId } from "react";
import { GUIDED_FIELDS, GUIDED_FIELD_CHARACTERS } from "../../services/guidedQuestion.js";

export default function GuidedQuestionFields({ fields, error, onField, onPrepare, fieldRefs }) {
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
