import { workspaceRequest, WorkspaceError } from "../../services/workspaceClient.js";
import { decodeNoteList, decodeNote, decodeForgottenNote, decodePreparedNote, noteId, noteRevision, noteScopeId, validNoteFields } from "./contract.js";

const base = "/me/context-notes";
const requireInput = value => { if (!value) throw new WorkspaceError("invalid_input"); };
function intent(selected, scope) {
  requireInput(noteId(selected?.id) && noteRevision(selected.revision) && noteScopeId(scope?.id) && typeof scope.can_use === "boolean");
  return { schemaVersion: 1, expected_scope_id: scope.id, revision: selected.revision };
}
function request(path, body, method, { ownerId, ...options }) {
  requireInput(noteId(ownerId));
  return workspaceRequest(path, { ...options, method, body, timeout: 5000, maxBytes: 32768, expectedStatuses: method === "POST" && path === base ? [200, 201] : [200] });
}
export async function listContextNotes(options) {
  return decodeNoteList(await request(base, undefined, "GET", options), options.ownerId);
}
export async function readContextNote(selected, scope, options) {
  intent(selected, scope); requireInput(scope.can_use && selected.availability === "available");
  return decodeNote(await request(`${base}/${selected.id}`, undefined, "GET", options), options.ownerId, scope, selected);
}
export async function createContextNote(fields, scope, requestId, options) {
  requireInput(validNoteFields(fields) && noteScopeId(scope?.id) && scope.can_use === true && noteId(requestId));
  const body = { schemaVersion: 1, client_request_id: requestId, expected_scope_id: scope.id, ...fields };
  return decodeNote(await request(base, body, "POST", options), options.ownerId, scope, null, fields);
}
export async function saveContextNote(selected, fields, scope, options) {
  const expected = intent(selected, scope); requireInput(scope.can_use && validNoteFields(fields) && selected.revision < Number.MAX_SAFE_INTEGER);
  const body = { ...expected, ...fields };
  return decodeNote(await request(`${base}/${selected.id}`, body, "PATCH", options), options.ownerId, scope, { id: selected.id, revision: selected.revision + 1 }, fields);
}
export async function forgetContextNote(selected, scope, options) {
  const body = intent(selected, scope); requireInput(selected.revision < Number.MAX_SAFE_INTEGER);
  return decodeForgottenNote(await request(`${base}/${selected.id}/forget`, body, "POST", options), options.ownerId, scope, selected);
}
export async function prepareContextNote(selected, scope, options) {
  const body = intent(selected, scope); requireInput(scope.can_use && validNoteFields({ kind: selected.kind, label: selected.label, body: selected.body }));
  return decodePreparedNote(await request(`${base}/${selected.id}/prepare`, body, "POST", options), options.ownerId, scope, selected);
}
