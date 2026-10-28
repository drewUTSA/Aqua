import { WorkspaceError, workspaceRequest } from "../services/workspaceClient.js";
import { accountMethods, accountOwner, accountProfile, accountRevision, accountSessions, normalizedDisplayName } from "./accountContract.js";

function validInput(normalize) {
  try { return normalize(); } catch { throw new WorkspaceError("invalid_input"); }
}

export function normalizeDisplayName(value) {
  return validInput(() => normalizedDisplayName(value));
}

// Only transport controls are accepted. Callers cannot change the route,
// method, payload or accepted response status through the options object.
function transport({ signal, csrfToken, timeout } = {}) {
  return { signal, csrfToken, ...(timeout === undefined ? {} : { timeout }) };
}

async function validated(path, options, decode) {
  const value = await workspaceRequest(path, options);
  if (options.signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  try { return decode(value); } catch { throw new WorkspaceError("invalid_response"); }
}

export function readAccount(owner, options) {
  const expectedOwner = validInput(() => accountOwner(owner));
  return validated("/me", { ...transport(options), method: "GET", expectedStatuses: [200] }, (value) => accountProfile(value, expectedOwner));
}

export function saveAccountName(owner, input, options) {
  const expectedOwner = validInput(() => accountOwner(owner));
  const body = validInput(() => {
    if (!input || typeof input !== "object" || Array.isArray(input)
      || ![Object.prototype, null].includes(Object.getPrototypeOf(input))
      || Reflect.ownKeys(input).length !== 2 || !Object.hasOwn(input, "revision") || !Object.hasOwn(input, "name")
      || !Reflect.ownKeys(input).every((key) => Object.hasOwn(Object.getOwnPropertyDescriptor(input, key), "value"))) throw new Error("account_invalid");
    return { expectedRevision: accountRevision(input.revision), display_name: normalizedDisplayName(input.name) };
  });
  return validated("/me", { ...transport(options), method: "PATCH", body, expectedStatuses: [200] }, (value) => {
    const result = accountProfile(value, expectedOwner);
    if (result.user.name !== body.display_name || !(result.revision === body.expectedRevision
      || body.expectedRevision < Number.MAX_SAFE_INTEGER && result.revision === body.expectedRevision + 1)) throw new Error("account_invalid");
    return result;
  });
}

// These read DTOs intentionally contain no owner identifier. Their consumer
// must cancel and discard the entire read scope when authenticated owner changes.
export const readAccountMethods = (options) => validated("/me/methods", { ...transport(options), method: "GET", expectedStatuses: [200] }, accountMethods);
export const readAccountSessions = (options) => validated("/me/sessions", { ...transport(options), method: "GET", expectedStatuses: [200] }, accountSessions);
