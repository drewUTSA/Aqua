// Isolated UI fixture. Every API call below is synthetic and confined to this
// document; the production client, proof component and coordinator are real.
import React, { useState } from "react";
import { createRoot } from "react-dom/client";
import DataDeletionProvider, { useDataDeletion } from "../src/settings/DataDeletionProvider.jsx";
import { HISTORY_HEADER } from "../src/services/historyAuthority.js";
import { useGoogleAuth } from "../src/hooks/useGoogleAuth.js";
const owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", job = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const old = "f".repeat(64), fresh = "0".repeat(64), proof = "v2." + "p".repeat(43), challenge = "v2." + "c".repeat(43);
const initial = { status: "authenticated", demoMode: false, user: { id: owner }, csrfToken: "synthetic-csrf", canQuery: true };
let currentOwner = owner, currentCsrf = initial.csrfToken, serverRevision = old, signedOut = false;
const scenario = new URLSearchParams(location.search).get("scenario") || "history";
if (scenario === "expire") {
  const schedule = window.setTimeout.bind(window), currentTime = Date.now.bind(Date); let offset = 0;
  Date.now = () => currentTime() + offset;
  window.setTimeout = (callback, milliseconds, ...args) => milliseconds >= 599000 && milliseconds <= 600000
    ? schedule(() => { offset = 600001; callback(...args); }, 50) : schedule(callback, milliseconds, ...args);
}
let issued = null, stored = null, created = 0, reconciled = 0, verified = 0, retainedReceipt = null, state = "awaiting_authority";
const counts = { creates: 0, reconciles: 0, verifications: 0, invalid: 0, external: 0 };
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json", [HISTORY_HEADER]: serverRevision } });
const session = () => ({ user: { id: currentOwner, email: "synthetic@example.test", name: "Synthetic", picture: "" }, csrf_token: currentCsrf, can_query: true });
const envelope = () => ({ schemaVersion: 1, user_id: owner, job: { id: job, intent_id: stored.intent_id, scope: stored.scope, state, accepted: state !== "awaiting_authority", cleanup_complete: state === "complete", created_at: new Date(created).toISOString(), receipt_expires_at: new Date(created + 600000).toISOString() }, history_revision: fresh });
const caps = { profile_edit: true, method_list: true, session_list: true, recent_proof: true, email_change: false, password_change: false, password_add: false, google_link: false, google_unlink: false, session_revoke: true, sessions_revoke_all: true, notification_delivery: false, in_app_notifications: true };
window.fetch = async (path, options = {}) => {
  const headers = new Headers(options.headers), body = options.body ? JSON.parse(options.body) : null;
  const invalid = () => { counts.invalid++; throw Error("synthetic_contract_failure"); };
  if (typeof path !== "string" || !path.startsWith("/api/")) { counts.external++; return invalid(); }
  if (path === "/api/auth/me") return signedOut ? new Response(null, { status: 401 }) : json(session());
  if (path === "/api/auth/config") return json({ client_id: "123-synthetic.apps.googleusercontent.com", nonce: "synthetic-nonce", csrf_token: "anonymous-csrf", capabilities: { google_login: false } });
  if (path === "/api/v1/auth/bootstrap?action=login") return json({ csrf_token: "anonymous-csrf", capabilities: { google_login: false, password_login: true, durable_sessions: true }, password_policy: { minimum_length: 15, maximum_length: 128, normalization: "NFC" } });
  if (path === "/api/v1/auth/password-login") {
    if (headers.get("X-CSRF-Token") !== "anonymous-csrf") return invalid();
    currentOwner = id; currentCsrf = "replacement-csrf"; serverRevision = old; signedOut = false; return json(session());
  }
  if (path === "/api/v1/me/methods") return json({ schemaVersion: 1, password: { linked: true, available: true, changed_at: new Date().toISOString() }, google: { linked: false, available: false, identities: [] }, capabilities: caps });
  if (headers.get("X-CSRF-Token") !== initial.csrfToken || options.method !== "POST") return invalid();
  if (path === "/api/v1/me/reauth-challenges") {
    if (Object.keys(body).sort().join() !== "operation,target_intent_id" || !["history_delete", "account_delete"].includes(body.operation)) return invalid();
    issued = body; return json({ schemaVersion: 1, challenge_id: id, challenge_token: challenge, expires_at: new Date(Date.now() + 240000).toISOString(), methods: ["password"] });
  }
  if (path === "/api/v1/me/reauth/password") {
    if (body.target_intent_id !== issued?.target_intent_id || body.operation !== issued.operation || body.password !== "Synthetic verification password 27" || body.challenge_id !== id || body.challenge_token !== challenge) return invalid();
    verified++; counts.verifications = verified;
    return json({ schemaVersion: 1, proof_token: proof, expires_at: new Date(Date.now() + 180000).toISOString() });
  }
  if (path === "/api/v1/me/data-deletions") {
    const scope = issued.operation === "history_delete" ? "chat_history_v1" : "account_v1";
    if (Object.keys(body).sort().join() !== "confirmation,intent_id,proof_token,receipt_token,scope" || body.intent_id !== issued.target_intent_id || body.scope !== scope || body.proof_token !== proof || body.receipt_token === proof || !/^v2\.[A-Za-z0-9_-]{43}$/.test(body.receipt_token) || body.confirmation !== (scope === "account_v1" ? "DELETE ACCOUNT" : "DELETE HISTORY") || headers.get(HISTORY_HEADER) !== old || counts.creates) return invalid();
    stored = { intent_id: body.intent_id, scope }; retainedReceipt = body.receipt_token; created = Date.now(); counts.creates++;
    serverRevision = fresh; signedOut = scope === "account_v1";
    if (scenario.includes("uncertain")) return new Response(null, { status: 503 });
    state = "accepted"; return json(envelope(), 202);
  }
  if (path === "/api/v1/me/data-deletions/by-intent/" + stored?.intent_id) {
    if (Object.keys(body).length || headers.get("X-Aqua-Deletion-Receipt") !== retainedReceipt || headers.has(HISTORY_HEADER)) return invalid();
    reconciled++; counts.reconciles = reconciled; return json(envelope());
  }
  return invalid();
};
function Entry() {
  const deletion = useDataDeletion();
  return <><button data-open-history onClick={() => deletion.open("chat_history_v1")}>Review history deletion</button><button data-open-account onClick={() => deletion.open("account_v1")}>Review account deletion</button></>;
}
function Private() {
  const [draft, setDraft] = useState("");
  return <section data-private-content><label>Draft<input data-private-draft value={draft} onChange={event => setDraft(event.target.value)} /></label></section>;
}
function Fixture() {
  const auth = useGoogleAuth({ demoMode: false });
  window.deletionFixture = {
    counts: () => ({ ...counts }), state: next => { state = next; },
    login: () => auth.authenticatePassword("synthetic@example.test", "Synthetic verification password 27"),
    receiptPresentInStorage: () => [localStorage, sessionStorage].some(storage => Object.values(storage).some(value => value.includes(retainedReceipt || "value-not-stored")))
  };
  return <DataDeletionProvider auth={auth}>{({ privateEpoch, privateBlocked }) => <>
    <Entry />{auth.user && !privateBlocked && <Private key={`${auth.historyEpoch}:${privateEpoch}`} />}
    <p data-auth-state>{auth.status}</p>
  </>}</DataDeletionProvider>;
}
createRoot(document.getElementById("root")).render(<Fixture />);
