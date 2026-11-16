// Local draft preparation only. User text never supplies schema or permission.
export const GUIDED_FIELDS = Object.freeze([
  Object.freeze({ id: "measure", label: "What should Aqua measure? (required)", draftLabel: "Measure" }),
  Object.freeze({ id: "grouping", label: "Group by (optional)", draftLabel: "Grouping" }),
  Object.freeze({ id: "period", label: "Time period (optional)", draftLabel: "Time period" }),
  Object.freeze({ id: "filters", label: "Filters (optional)", draftLabel: "Filters" }),
]);
export const GUIDED_FIELD_CHARACTERS = 400;
const encoder = new TextEncoder();
const controls = /[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/u;
const surrogate = /[\uD800-\uDFFF]/u;
const fieldIds = new Set(GUIDED_FIELDS.map((field) => field.id));

export class GuidedQuestionError extends Error {
  constructor(code, field = "measure") { super(code); this.code = code; this.field = field; }
}

export const emptyGuidedQuestion = () => Object.fromEntries(GUIDED_FIELDS.map(({ id }) => [id, ""]));

export function guidedFieldValue(field, value) {
  if (!fieldIds.has(field) || typeof value !== "string") throw new GuidedQuestionError("invalid_fields", field);
  if (value.length > GUIDED_FIELD_CHARACTERS || encoder.encode(value).length > 1600) throw new GuidedQuestionError("field_too_long", field);
  if (controls.test(value) || surrogate.test(value)) throw new GuidedQuestionError("field_controls", field);
  return value;
}

export function prepareGuidedQuestion(fields) {
  if (!fields || typeof fields !== "object" || Array.isArray(fields) || ![Object.prototype, null].includes(Object.getPrototypeOf(fields))) throw new GuidedQuestionError("invalid_fields");
  const entries = Object.getOwnPropertyDescriptors(fields);
  if (Reflect.ownKeys(entries).length !== GUIDED_FIELDS.length || GUIDED_FIELDS.some(({ id }) => !Object.hasOwn(entries, id) || !Object.hasOwn(entries[id], "value"))) throw new GuidedQuestionError("invalid_fields");
  const values = Object.fromEntries(GUIDED_FIELDS.map(({ id }) => [id, guidedFieldValue(id, entries[id].value).normalize("NFC").trim().replace(/\s+/gu, " ")]));
  if (!values.measure) throw new GuidedQuestionError("measure_required");
  const missing = GUIDED_FIELDS.filter(({ id }) => !values[id]).map(({ id }) => id);
  const question = ["Please help me analyze the following.",
    ...GUIDED_FIELDS.map(({ id, draftLabel }) => `${draftLabel}: ${values[id] || "Not specified."}`),
    "Do not invent omitted details, definitions or units."].join("\n");
  if (question.length > 2000 || encoder.encode(question).length > 8000) throw new GuidedQuestionError("draft_too_long");
  return { question, missing };
}

export function guidedQuestionMessage(error) {
  if (error?.code === "measure_required") return "Enter what you want to measure.";
  if (error?.code === "field_too_long") return "Keep this answer to 400 characters or fewer.";
  if (error?.code === "field_controls") return "Use plain text without control characters.";
  if (error?.code === "draft_too_long") return "Shorten the answers so the draft fits in 2,000 characters.";
  return "Review the guide fields and prepare the draft again.";
}
