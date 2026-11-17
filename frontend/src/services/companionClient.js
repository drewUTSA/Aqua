// Reviewed help only. Data questions still require the existing explicit submit.
import { workspaceRequest, WorkspaceError } from "./workspaceClient.js";

const MAX_BYTES = 32768, revision = /^[a-f0-9]{64}$/, identifier = /^[a-z][a-z0-9_-]{0,63}$/;
const requireContract = (condition) => { if (!condition) throw new WorkspaceError("invalid_response"); };
const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const keys = (value, names) => record(value) && Object.keys(value).length === names.length && names.every((name) => Object.hasOwn(value, name));
const text = (value, max) => typeof value === "string" && value.trim().length > 0 && new TextEncoder().encode(value).length <= max
  && !/[\u0000-\u0008\u000b-\u001f\u007f]/u.test(value) && !/[\uD800-\uDFFF]/u.test(value);

function questionText(question) {
  if (!text(question, 8000) || question.length > 2000) throw new WorkspaceError("invalid_input");
  return question;
}
export { questionText as boundedCompanionQuestion };

export function companionCapabilities(value) {
  requireContract(keys(value, ["schemaVersion", "advisory", "selection", "pack_revision", "capabilities"])
    && value.schemaVersion === 1 && value.advisory === true && value.selection === "explicit" && revision.test(value.pack_revision)
    && Array.isArray(value.capabilities) && value.capabilities.length >= 1 && value.capabilities.length <= 2);
  const seen = new Set();
  for (const tool of value.capabilities) {
    requireContract(keys(tool, ["id", "behavior"]) && !seen.has(tool.id)
      && ((tool.id === "app_help" && tool.behavior === "reviewed_lookup")
        || (tool.id === "authorized_question" && tool.behavior === "seed_draft")));
    seen.add(tool.id);
  }
  requireContract(seen.has("app_help"));
  return { ...value, capabilities: value.capabilities.map((tool) => ({ ...tool })) };
}

export function companionAnswer(value) {
  requireContract(keys(value, ["schemaVersion", "status", "capability_id", "method", "message", "citations", "pack_revision"])
    && value.schemaVersion === 1 && ["answered", "abstained"].includes(value.status)
    && value.capability_id === "app_help" && value.method === "reviewed_lookup" && revision.test(value.pack_revision)
    && text(value.message, 8192) && Array.isArray(value.citations) && value.citations.length <= 3);
  requireContract(value.status === "answered" ? value.citations.length > 0 : value.citations.length === 0);
  const seen = new Set();
  for (const citation of value.citations) {
    requireContract(keys(citation, ["id", "title", "revision"]) && typeof citation.id === "string" && identifier.test(citation.id)
      && !seen.has(citation.id) && text(citation.title, 120) && citation.revision === value.pack_revision);
    seen.add(citation.id);
  }
  return { ...value, citations: value.citations.map((citation) => ({ ...citation })) };
}

export async function getCompanionCapabilities(options = {}) {
  const value = await workspaceRequest("/companion/capabilities", { ...options, method: "GET", body: undefined, maxBytes: MAX_BYTES, timeout: 5000 });
  return companionCapabilities(value);
}

export async function askCompanionHelp(question, options = {}) {
  const body = { schemaVersion: 1, question: questionText(question) };
  const value = await workspaceRequest("/companion/help", { ...options, method: "POST", body, maxBytes: MAX_BYTES, timeout: 5000, expectedStatuses: [200] });
  return companionAnswer(value);
}

export function prepareCompanionDraft(question, menu) {
  // Advisory convenience only: submitQuestion and the server reauthorize later.
  const current = companionCapabilities(menu);
  if (!current.capabilities.some((tool) => tool.id === "authorized_question")) throw new WorkspaceError("forbidden", 403);
  return questionText(question);
}
