import { emptyGuidedQuestion, guidedFieldValue } from "../../services/guidedQuestion.js";

export const FOLLOWUPS = Object.freeze({ verify_scope: "Narrow or verify this result", missing_values: "Investigate missing values", compare_field: "Compare this field" });
export function resultFollowupFields(intent, label) {
  if (!Object.hasOwn(FOLLOWUPS, intent) || typeof label !== "string") return null;
  const measure = ({ verify_scope: `Summarize the field "${label}" with the scope I specify.`, missing_values: `Count rows with a missing value in the field "${label}".`, compare_field: `Compare values in the field "${label}".` })[intent];
  const fields = emptyGuidedQuestion();
  try { fields.measure = guidedFieldValue("measure", measure); } catch { /* Keep an unfit suggestion blank rather than truncating it. */ }
  return fields;
}
