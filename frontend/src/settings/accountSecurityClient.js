import { WorkspaceError, workspaceRequest } from "../services/workspaceClient.js";
import { accountOwner } from "./accountContract.js";
import { actionChallenge, actionPassword, actionProof, actionTarget, actionToken, passwordChanged, sessionsRevoked } from "./accountSecurityContract.js";

const input = normalize => { try { return normalize(); } catch { throw new WorkspaceError("invalid_input", 422); } };
function controls({ signal, csrfToken, timeout } = {}) { return { signal, csrfToken, ...(timeout === undefined ? {} : { timeout }) }; }
async function action(path, method, body, options, decode) {
  const transport = controls(options);
  const value = await workspaceRequest(path, { ...transport, method, body, expectedStatuses: [200] });
  if (transport.signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  try { return decode(value); } catch { throw new WorkspaceError("invalid_response"); }
}
export function createAccountChallenge(target, options) {
  return action("/me/reauth-challenges", "POST", input(() => actionTarget(target)), options, actionChallenge);
}
export function verifyAccountPassword(target, challenge, password, options) {
  const checked = input(() => actionChallenge(challenge));
  const body = input(() => {
    return { ...actionTarget(target), challenge_id: checked.challenge_id, challenge_token: checked.challenge_token, password: actionPassword(password) };
  });
  return action("/me/reauth/password", "POST", body, options, value => actionProof(value, checked));
}
export function changeAccountPassword(proof, password, options) {
  const body = input(() => ({ proof_token: actionToken(proof), new_password: actionPassword(password, true) }));
  return action("/me/password", "PUT", body, options, passwordChanged);
}
export function revokeAccountSession(id, proof, current, options) {
  const target = input(() => { if (typeof current !== "boolean") throw Error(); return accountOwner(id); });
  return action(`/me/sessions/${target}/revocations`, "POST", input(() => ({ proof_token: actionToken(proof) })), options, value => sessionsRevoked(value, current));
}
export function revokeAllAccountSessions(proof, options) {
  return action("/me/session-revocations", "POST", input(() => ({ proof_token: actionToken(proof) })), options, value => sessionsRevoked(value, true));
}
