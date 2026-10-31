import { WorkspaceError, workspaceRequest } from "../services/workspaceClient.js";
import { accountOwner, accountRevision } from "./accountContract.js";
import { actionTarget, actionToken, actionProof, actionPassword, actionEmail, actionRecord } from "./accountSecurityContract.js";
import { googleCredential, googleActionChallenge, googleCandidate, identityMutation, mailRequest, mailToken, notificationSnapshot, notificationValues } from "./accountIdentityContract.js";
const input = normalize => { try { return normalize(); } catch { throw new WorkspaceError("invalid_input", 422); } };
async function request(path, method, body, { signal, csrfToken, timeout } = {}, decode) {
  const value = await workspaceRequest(path, { signal, csrfToken, ...(timeout === undefined ? {} : { timeout }), method, ...(body ? { body } : {}), expectedStatuses: [200] });
  if (signal?.aborted) throw new DOMException("Request cancelled", "AbortError");
  try { return decode(value); } catch { throw new WorkspaceError("invalid_response"); }
}
export function createGoogleAccountChallenge(target, identityId, options) {
  return request("/me/reauth/google-challenges", "POST", input(() => ({ ...actionTarget(target), identity_id: accountOwner(identityId) })), options, googleActionChallenge);
}
export function verifyAccountGoogle(target, challenge, credential, options) {
  const checked = input(() => googleActionChallenge(challenge));
  return request("/me/reauth/google", "POST", input(() => ({ ...actionTarget(target), challenge_id: checked.challenge_id, challenge_token: checked.challenge_token, credential: googleCredential(credential) })), options, value => actionProof(value, checked));
}
export function createGoogleLinkChallenge(proof, options) {
  return request("/me/google-link-challenges", "POST", input(() => ({ proof_token: actionToken(proof) })), options, googleActionChallenge);
}
export function verifyGoogleLinkCandidate(challenge, credential, options) {
  const checked = input(() => googleActionChallenge(challenge));
  return request("/me/google-link-candidates", "POST", input(() => ({ challenge_id: checked.challenge_id, challenge_token: checked.challenge_token, credential: googleCredential(credential) })), options, value => googleCandidate(value, checked));
}
export function linkAccountGoogle(proof, candidate, options) {
  return request("/me/google-links", "POST", input(() => ({ proof_token: actionToken(proof), candidate_token: actionToken(candidate) })), options, value => identityMutation(value, "linked"));
}
export function unlinkAccountGoogle(identityId, proof, options) {
  return request(`/me/methods/google/${input(() => accountOwner(identityId))}/revocations`, "POST", input(() => ({ proof_token: actionToken(proof) })), options, value => identityMutation(value, "unlinked"));
}
export function createPasswordEnrollment(proof, options) {
  return request("/me/password-enrollments", "POST", input(() => ({ proof_token: actionToken(proof) })), options, value => mailRequest(value, "password_add"));
}
export function createEmailChangeRequest(proof, newEmail, options) {
  return request("/me/email-change-requests", "POST", input(() => ({ proof_token: actionToken(proof), new_email: actionEmail(newEmail) })), options, value => mailRequest(value, "email_change"));
}
function completion(value, password) {
  actionRecord(value, ["proof_token", "request_id", "request_token", "email_token", password ? "new_password" : "old_email_token"]);
  return { proof_token: actionToken(value.proof_token), request_id: accountOwner(value.request_id), request_token: actionToken(value.request_token), email_token: mailToken(value.email_token),
    ...(password ? { new_password: actionPassword(value.new_password, true) } : { old_email_token: mailToken(value.old_email_token) }) };
}
export function addAccountPassword(body, options) {
  return request("/me/password", "POST", input(() => completion(body, true)), options, value => identityMutation(value, "password_added"));
}
export function changeAccountEmail(body, options) {
  return request("/me/email", "PUT", input(() => completion(body, false)), options, value => identityMutation(value, "email_changed"));
}
export function readNotificationSettings(owner, options) {
  input(() => accountOwner(owner));
  return request("/me/notification-settings", "GET", null, options, value => notificationSnapshot(value, owner));
}
export function saveNotificationSettings(owner, body, options) {
  input(() => accountOwner(owner));
  const value = input(() => { actionRecord(body, ["expectedRevision", "in_app_success", "preview"]); return { expectedRevision: accountRevision(body.expectedRevision), ...notificationValues({ in_app_success: body.in_app_success, preview: body.preview }) }; });
  return request("/me/notification-settings", "PUT", value, options, result => { const snapshot = notificationSnapshot(result, owner); if (snapshot.revision < value.expectedRevision || snapshot.revision>value.expectedRevision+1 || Object.entries(snapshot.values).some(([key, item]) => item !== value[key])) throw Error(); return snapshot; });
}
