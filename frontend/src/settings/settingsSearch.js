import { CATEGORIES } from "./controls.js";

// Fixed UI labels only. Operational controls save separately from preferences;
// indexing their names must never execute them or broaden capabilities.
const KEYWORDS = {
  notifications: "consent success messages notices",
  account: "profile display name change email password Google linked identities sign-in sessions revoke",
  privacy: "import export download preference files delete deletion history account personal data",
};
export function searchSettings(value) {
  if (typeof value !== "string") return [];
  const terms = value.slice(0, 100).trim().toLocaleLowerCase("en").split(/\s+/).filter(Boolean);
  if (!terms.length) return [];
  const matches = (text) => terms.every((term) => text.toLocaleLowerCase("en").includes(term));
  return CATEGORIES.map((category) => ({ ...category, fields: category.fields.filter((field) =>
    matches(`${category.title} ${field.label} ${field.help}`)) }))
    .filter((category) => category.fields.length || matches(`${category.title} ${category.description} ${KEYWORDS[category.id] || ""}`));
}
