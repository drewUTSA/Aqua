import { WorkspaceError } from "../../services/workspaceClient.js";
import { accountInstant, compareAccountInstants } from "../../settings/accountContract.js";

const encoder = new TextEncoder(), uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/, hex = /^[a-f0-9]{64}$/;
export const noteLimits = Object.freeze({ active_notes: 20, label_characters: 120, label_bytes: 512, body_utf16_units: 2000,
  body_bytes: 2048, draft_utf16_units: 2000, draft_bytes: 8000 });
const require = value => { if (!value) throw new WorkspaceError("invalid_response"); };
export const noteId = value => typeof value === "string" && uuid.test(value);
export const noteRevision = value => Number.isSafeInteger(value) && value >= 1;
export const noteScopeId = value => typeof value === "string" && hex.test(value);
function keys(value, names) {
  if (!value || typeof value !== "object" || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(descriptors).length === names.length && names.every(name => Object.hasOwn(descriptors, name) && Object.hasOwn(descriptors[name], "value"));
}
function list(value) {
  return Array.isArray(value) && value.length <= 20 && Reflect.ownKeys(value).length === value.length + 1
    && Array.from({ length: value.length }, (_, i) => Object.getOwnPropertyDescriptor(value, i)).every(item => item && Object.hasOwn(item, "value"));
}
const kind = value => ["note", "metric_definition"].includes(value);
const clean = value => typeof value === "string" && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value.replace(/[\t\n]/g, ""));
export const validNoteLabel = value => typeof value === "string" && value.trim() === value && value.length > 0
  && [...value].length <= 120 && encoder.encode(value).length <= 512 && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
export const validNoteBody = value => clean(value) && value.trim().length > 0 && value.length <= 2000 && encoder.encode(value).length <= 2048;
export const validNoteDraft = value => clean(value) && value.trim().length > 0 && value.length <= 2000 && encoder.encode(value).length <= 8000;
export const noteBytes = value => encoder.encode(value).length;
export function validNoteFields(value) {
  return keys(value, ["kind", "label", "body"]) && kind(value.kind) && validNoteLabel(value.label) && validNoteBody(value.body);
}
function times(value) {
  try { accountInstant(value.created_at); accountInstant(value.updated_at); require(compareAccountInstants(value.created_at, value.updated_at) <= 0); }
  catch { throw new WorkspaceError("invalid_response"); }
}
function metadata(value) {
  require(keys(value, ["id", "revision", "availability", "label", "kind", "created_at", "updated_at"]) && noteId(value.id) && noteRevision(value.revision));
  if (value.availability === "available") { require(validNoteLabel(value.label) && kind(value.kind)); times(value); }
  else require(value.availability === "unavailable" && value.label === "Unavailable saved context" && value.kind === null && value.created_at === null && value.updated_at === null);
}
function fullNote(value) {
  require(keys(value, ["id", "revision", "kind", "label", "body", "created_at", "updated_at"]) && noteId(value.id) && noteRevision(value.revision)
    && validNoteFields({ kind: value.kind, label: value.label, body: value.body })); times(value);
}
function envelope(value, names, ownerId, scope) {
  require(noteId(ownerId) && keys(value, ["schemaVersion", "owner_id", "scope", "unverified", "execution_enabled", ...names])
    && value.schemaVersion === 1 && value.owner_id === ownerId && value.unverified === true && value.execution_enabled === false
    && keys(value.scope, ["id", "can_use"]) && noteScopeId(value.scope.id) && typeof value.scope.can_use === "boolean");
  if (scope && (value.scope.id !== scope.id || value.scope.can_use !== scope.can_use)) throw new WorkspaceError("conflict", 409);
}
function bound(value) { require(encoder.encode(JSON.stringify(value)).length <= 32768); return structuredClone(value); }
export function decodeNoteList(value, ownerId) {
  envelope(value, ["items", "limits"], ownerId);
  require(list(value.items) && keys(value.limits, Object.keys(noteLimits)) && Object.entries(noteLimits).every(([key, limit]) => value.limits[key] === limit));
  const seen = new Set();
  for (const item of value.items) { metadata(item); require(!seen.has(item.id) && (value.scope.can_use || item.availability === "unavailable")); seen.add(item.id); }
  return bound(value);
}
export function decodeNote(value, ownerId, scope, expected, fields) {
  envelope(value, ["note"], ownerId, scope); require(value.scope.can_use); fullNote(value.note);
  if (expected && (value.note.id !== expected.id || value.note.revision !== expected.revision)) throw new WorkspaceError("conflict", 409);
  if (expected?.availability === "available") require(value.note.kind === expected.kind && value.note.label === expected.label
    && value.note.created_at === expected.created_at && value.note.updated_at === expected.updated_at);
  if (fields) require(value.note.kind === fields.kind && value.note.label === fields.label && value.note.body === fields.body);
  return bound(value);
}
export function decodeForgottenNote(value, ownerId, scope, selected) {
  envelope(value, ["deleted"], ownerId, scope);
  require(keys(value.deleted, ["id", "revision"]) && value.deleted.id === selected.id && noteRevision(value.deleted.revision) && value.deleted.revision === selected.revision + 1);
  return bound(value);
}
export function decodePreparedNote(value, ownerId, scope, selected) {
  envelope(value, ["source", "draft", "requires_review"], ownerId, scope);
  require(value.scope.can_use && keys(value.source, ["id", "revision", "kind", "label"]) && value.source.id === selected.id
    && value.source.revision === selected.revision && value.source.kind === selected.kind && value.source.label === selected.label
    && value.requires_review === true && validNoteBody(value.draft) && value.draft === selected.body);
  return bound(value);
}
