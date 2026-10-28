import { assertUniqueJsonKeys } from "./strictJson.js";
// Portable preferences are bounded presentation data, never capabilities or code.
export const SCHEMA_VERSION = 1;
export const MAX_PREFERENCE_BYTES = 64 * 1024;
const choice = (values, fallback) => ({ kind: "choice", values, default: fallback });
const toggle = (fallback = true) => ({ kind: "boolean", default: fallback });
export const ACCOUNT_RULES = {
  theme: choice(["opal", "light", "system"], "opal"),
  accent: choice(["pearl", "sage", "slate", "amber"], "pearl"),
  density: choice(["comfortable", "compact"], "comfortable"),
  specks: choice(["subtle", "off"], "subtle"),
  surface: choice(["solid", "depth"], "solid"),
  font: choice(["manrope", "system"], "manrope"),
  sidebar_sections: { kind: "order", values: ["projects", "recents", "prompts"], default: ["projects", "recents", "prompts"] },
  recents_count: choice([5, 10, 20], 10),
  suggestions: toggle(), timestamps: choice(["compact", "always", "hidden"], "compact"), wrap_code: toggle(),
  initial_result_view: choice(["chart", "table"], "chart"),
  palette: choice(["categorical", "sequential", "diverging"], "categorical"),
  legend: choice(["auto", "show", "hide"], "auto"), grid: choice(["subtle", "standard", "minimal"], "subtle"),
  preserve_exploration: toggle(), table_density: choice(["comfortable", "compact"], "comfortable"),
  table_page_size: choice([10, 25, 50], 25), precision: choice(["auto", "0", "2", "4", "6"], "auto"),
  expanded_summaries: toggle(), locale: choice(["en-US", "en-GB"], "en-US"),
  timezone: choice(["device", "UTC", "America/Chicago", "America/New_York", "America/Los_Angeles", "Europe/London"], "device"),
  date_style: choice(["medium", "short", "long"], "medium"), time_format: choice(["locale", "12", "24"], "locale")
};
export const DEVICE_RULES = {
  contrast: choice(["standard", "increased"], "standard"), text_scale: choice([100, 112.5, 125, 150], 100),
  line_spacing: choice(["standard", "relaxed"], "standard"), sidebar: choice(["expanded", "collapsed"], "expanded"),
  conversation_width: choice(["comfortable", "focused", "wide"], "comfortable"),
  split_percent: { kind: "integer", min: 25, max: 65, default: 38 },
  send_shortcut: choice(["enter", "modified_enter"], "enter"), auto_scroll: choice(["follow", "manual"], "follow"),
  chart_motion: choice(["system", "off"], "system"), motion: choice(["system", "reduce"], "system"),
  announcements: choice(["standard", "reduced"], "standard")
};
export const clone = (value) => JSON.parse(JSON.stringify(value));
export function equal(left, right) {
  if (Object.is(left, right)) return true;
  if (Array.isArray(left) || Array.isArray(right)) return Array.isArray(left) && Array.isArray(right)
    && left.length === right.length && left.every((value, index) => equal(value, right[index]));
  if (!isRecord(left) || !isRecord(right)) return false;
  const keys = Object.keys(left);
  return keys.length === Object.keys(right).length && keys.every((key) => Object.hasOwn(right, key) && equal(left[key], right[key]));
}
const defaults = (rules) => Object.fromEntries(Object.entries(rules).map(([key, rule]) => [key, clone(rule.default)]));
export const ACCOUNT_DEFAULTS = Object.freeze(defaults(ACCOUNT_RULES));
export const DEVICE_DEFAULTS = Object.freeze(defaults(DEVICE_RULES));
const banned = new Set(["__proto__", "prototype", "constructor"]);
export const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));
export class PreferenceValidationError extends Error {
  constructor(message = "This preference file is not supported.") { super(message); this.name = "PreferenceValidationError"; }
}
function requireValid(condition, message) { if (!condition) throw new PreferenceValidationError(message); }
export function validateValues(values, scope, { partial = false } = {}) {
  const rules = scope === "account" ? ACCOUNT_RULES : scope === "device" ? DEVICE_RULES : null;
  requireValid(rules && isRecord(values), "Preferences must be a plain object.");
  const keys = Object.keys(values);
  requireValid(keys.every((key) => !banned.has(key) && Object.hasOwn(rules, key)), "Unknown or protected preference fields are not allowed.");
  requireValid(partial || Object.keys(rules).every((key) => Object.hasOwn(values, key)), "The saved preference record is incomplete.");
  for (const key of keys) {
    const rule = rules[key], value = values[key];
    const valid = rule.kind === "choice" ? rule.values.some((allowed) => typeof allowed === typeof value && allowed === value)
      : rule.kind === "boolean" ? typeof value === "boolean"
        : rule.kind === "integer" ? Number.isSafeInteger(value) && value >= rule.min && value <= rule.max
          : Array.isArray(value) && value.length <= rule.values.length && new Set(value).size === value.length
            && value.every((item) => typeof item === "string" && rule.values.includes(item));
    requireValid(valid, `${key.replaceAll("_", " ")} has an unsupported value.`);
  }
  return clone(values);
}
export function parseImport(text) {
  requireValid(typeof text === "string" && new TextEncoder().encode(text).length <= MAX_PREFERENCE_BYTES, "Preference files must be 64 KiB or smaller.");
  let value;
  try { assertUniqueJsonKeys(text); value = JSON.parse(text); } catch (error) {
    throw new PreferenceValidationError(error.message?.startsWith("Choose JSON") ? error.message : "Choose a valid JSON preference file.");
  }
  requireValid(isRecord(value) && Object.keys(value).every((key) => ["schemaVersion", "account", "device"].includes(key)), "The file contains unknown or protected fields.");
  requireValid(value.schemaVersion === SCHEMA_VERSION, "This preference schema version is not supported.");
  requireValid(Object.hasOwn(value, "account"), "The file must contain account preferences.");
  const result = { schemaVersion: SCHEMA_VERSION, account: validateValues(value.account, "account", { partial: true }) };
  if (Object.hasOwn(value, "device")) result.device = validateValues(value.device, "device", { partial: true });
  return result;
}
export function exportPreferences(account, device) {
  const result = { schemaVersion: SCHEMA_VERSION, account: validateValues(account, "account") };
  if (device !== undefined) result.device = validateValues(device, "device");
  return JSON.stringify(result, null, 2);
}
export function preferenceResponse(body) {
  requireValid(isRecord(body) && body.schemaVersion === SCHEMA_VERSION && Number.isSafeInteger(body.revision) && body.revision >= 1, "AQUA returned an unsupported preference record.");
  const values = validateValues(body.values, "account");
  requireValid(isRecord(body.capabilities) && Object.keys(body.capabilities).length <= 32, "AQUA returned unsupported preference capabilities.");
  requireValid(Object.entries(body.capabilities).every(([key, value]) => !banned.has(key)
    && /^[a-z][a-z_]{0,47}$/.test(key) && (typeof value === "boolean"
      || key === "interface_languages" && Array.isArray(value) && value.length === 1 && value[0] === "en")), "AQUA returned unsupported preference capabilities.");
  return { schemaVersion: SCHEMA_VERSION, revision: body.revision, values, capabilities: clone(body.capabilities) };
}
