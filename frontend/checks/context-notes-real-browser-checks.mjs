// Actual FastAPI/session/SQL via the bounded disposable JSONL fixture. No mocked
// notes DTOs, provider, analytical dataset, production host or training packet.
import assert from "node:assert/strict";
import { decodeNoteList, decodeNote, decodePreparedNote } from "../src/features/contextNotes/contract.js";

export const REAL_NOTES_GOLD = Object.freeze({ label: "Orchid operations note", kind: "note",
  body: "Fictional team note: review volume by month.\n\tLiteral <metric> text.",
  correctedLabel: "Orchid working definition", correctedKind: "metric_definition",
  correctedBody: "User claim: Orchid volume means completed fictional items. Verify before use.",
  draftSuffix: " Ask me to confirm the period.", newerDraft: "Keep my newer fictional question." });
export const REAL_NOTES_CASES = Object.freeze([
  "ungranted metadata-only library", "grant refresh without help", "keyboard explicit create", "metadata and explicit body read",
  "inert authored markup", "exact prepare without execution", "keyboard reviewed Apply without Send", "preview leaves stored bytes unchanged",
  "full correction and revision fence", "scope authority and CSRF negatives", "confirmed available forget", "second owned race note",
  "late prepare after close", "late prepare after composer change", "actual revoke hides old contents", "regrant does not revive old scope",
  "forget unavailable and create current note", "actual history generation fences held response", "actual cookie owner replacement",
  "foreign note operations denied", "320px doubled text and native keyboard", "zero execution and final private cleanup"
]);
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/, hex = /^[a-f0-9]{64}$/;
const own = (value, key) => {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw Error("real_notes_record_invalid");
  const descriptor = Object.getOwnPropertyDescriptor(value, key);
  if (!descriptor || !Object.hasOwn(descriptor, "value")) throw Error("real_notes_record_invalid");
  return descriptor.value;
};
const exact = (value, keys) => value && typeof value === "object" && !Array.isArray(value)
  && Reflect.ownKeys(value).length === keys.length && keys.every(key => Object.hasOwn(Object.getOwnPropertyDescriptor(value, key) || {}, "value"));
const positive = value => Number.isSafeInteger(value) && value >= 1;
function loopback(value) {
  if (typeof value !== "string" || !/^http:\/\/127\.0\.0\.1:[1-9][0-9]{3,4}$/.test(value)) throw Error("real_notes_origin_invalid");
  const url = new URL(value); if (+url.port < 1024 || +url.port > 65535 || url.origin !== value) throw Error("real_notes_origin_invalid"); return value;
}
export function notesRealMode(journey, analysis, bank = false) {
  if (![null, "bank-demo", "context-notes"].includes(journey) || typeof analysis !== "boolean" || typeof bank !== "boolean"
    || journey === "context-notes" && (analysis || bank)) throw Error("real_notes_fixture_mode_invalid");
  return journey === "context-notes";
}
export function requireNotesReady(value, origin) {
  loopback(origin);
  for (const [key, expected] of Object.entries({ notes_fixture: true, schema_version: 10, workspace_analysis_fixture: false,
    dataset_grants: 0, max_requests: 256, max_seconds: 300, body_bytes_max: 16384, origin, network: "none", database_transport: "private_unix_socket" }))
    if (own(value, key) !== expected) throw Error("real_notes_readiness_invalid");
  if (own(own(value, "capabilities"), "workspace_analysis") !== false || own(value, "bank_demo_fixture") !== false) throw Error("real_notes_readiness_invalid");
  return true;
}
export function notesResponsePrivate(response) {
  const headers = own(response, "headers");
  if (!Array.isArray(headers)) throw Error("real_notes_headers_invalid");
  const cache = headers.filter(pair => Array.isArray(pair) && pair.length === 2 && typeof pair[0] === "string" && pair[0].toLowerCase() === "cache-control");
  return cache.length === 1 && typeof cache[0][1] === "string" && cache[0][1].split(",").some(value => value.trim().toLowerCase() === "no-store");
}
export function notesCleanupConfirmed(value) {
  try {
    for (const key of ["closed", "failed", "abandoned", "remaining", "armed", "captured", "released", "fulfilled", "verified_canceled"]) own(value, key);
    return value.closed === true && value.failed === false && value.abandoned === 0 && value.remaining === 0 && value.armed === false
      && Number.isSafeInteger(value.captured) && value.captured >= 0 && value.captured <= 4 && value.captured === value.released
      && Number.isSafeInteger(value.fulfilled) && value.fulfilled >= 0 && Number.isSafeInteger(value.verified_canceled) && value.verified_canceled >= 0
      && value.captured === value.fulfilled + value.verified_canceled;
  } catch { return false; }
}
export function notesStats(value) {
  const keys = ["id", "kind", "state", "notes", "chats", "messages", "analysis", "engine_calls", "enqueue_calls", "provider_calls", "forbidden_requests"];
  if (!exact(value, keys) || !Number.isSafeInteger(value.id) || value.id < 1 || value.kind !== "notes_stats" || typeof value.state !== "string"
    || !["ungranted", "granted", "revoked", "regranted", "history_advanced"].includes(value.state)
    || keys.slice(3).some(key => !Number.isSafeInteger(value[key]) || value[key] < 0)) throw Error("real_notes_stats_invalid");
  for (const key of keys.slice(4)) if (value[key] !== 0) throw Error("real_notes_execution_detected");
  return Object.fromEntries(keys.filter(key => key !== "id").map(key => [key, value[key]]));
}
export async function notesRealKey(send, key) {
  const codes = { Enter: 13, Tab: 9, Escape: 27, Home: 36, ArrowDown: 40 };
  if (!Object.hasOwn(codes, key)) throw Error("real_notes_key_invalid");
  for (const type of ["keyDown", "keyUp"]) await send("Input.dispatchKeyEvent", { type, key, code: key, windowsVirtualKeyCode: codes[key], modifiers: 0, ...(key === "Enter" ? { text: "\r" } : {}) });
}

// Evaluated against the rendered panel by Chrome. The editor disappears as
// soon as Forget starts, before the server has confirmed the deletion.
export function notesForgetConfirmed(panel, id) {
  return Boolean(panel?.querySelector("[role=status]")?.textContent.startsWith("Forgot this library entry."))
    && !panel.querySelector(`[data-notes-select="${id}"], [data-notes-forget-confirm], [data-notes-body]`);
}

const transportId = value => typeof value === "string" && /^[A-Za-z0-9._:-]{1,256}$/.test(value);
export function notesCancellationCleanupConfirmed(value) {
  try {
    for (const key of ["closed", "failed", "registered", "fulfilled", "verified_canceled", "pending"]) own(value, key);
    return value.closed === true && value.failed === false && value.pending === 0
      && [value.registered, value.fulfilled, value.verified_canceled].every(item => Number.isSafeInteger(item) && item >= 0 && item <= 4)
      && value.registered === value.fulfilled + value.verified_canceled;
  } catch { return false; }
}

// Only a matching actual Network.loadingFailed(canceled:true) can establish
// that THIS captured Fetch request was canceled. Navigation/shutdown guesses,
// error strings alone and an event for another request never establish it.
export class NotesCancellationEvidence {
  #origin; #tokens = new WeakMap(); #networks = new Map(); #fetches = new Set(); #closed = false; #failed = false;
  #registered = 0; #fulfilled = 0; #canceled = 0;
  constructor(origin) { this.#origin = loopback(origin); }
  bind(event) {
    if (this.#closed || this.#failed || this.#registered >= 4) throw Error("real_notes_cancellation_capacity");
    const fetchId = own(event, "requestId"), networkId = own(event, "networkId"), request = own(event, "request"), rawUrl = own(request, "url");
    if (!transportId(fetchId) || !transportId(networkId) || this.#networks.has(networkId) || this.#fetches.has(fetchId)
      || own(request, "method") !== "POST" || typeof rawUrl !== "string") throw Error("real_notes_cancellation_binding_invalid");
    const url = new URL(rawUrl), match = /^\/api\/v1\/me\/context-notes\/([a-f0-9-]{36})\/prepare$/.exec(url.pathname);
    if (url.origin !== this.#origin || rawUrl !== this.#origin + url.pathname || !match || !uuid.test(match[1])) throw Error("real_notes_cancellation_binding_invalid");
    const record = { fetchId, networkId, canceled: false, settled: false, finishing: false }, token = Object.freeze({});
    this.#tokens.set(token, record); this.#networks.set(networkId, record); this.#fetches.add(fetchId); this.#registered++; return token;
  }
  observe(event) {
    if (this.#closed) return false;
    if (!Object.hasOwn(event || {}, "canceled")) return false;
    const networkId = own(event, "requestId"), canceled = own(event, "canceled");
    if (!transportId(networkId) || typeof canceled !== "boolean") throw Error("real_notes_cancellation_event_invalid");
    if (!canceled) return false;
    const record = this.#networks.get(networkId); if (!record || record.settled) return false;
    record.canceled = true; return true;
  }
  async finish(token, fulfill) {
    const record = token && this.#tokens.get(token);
    if (this.#closed || this.#failed || !record || record.settled || record.finishing || typeof fulfill !== "function") throw Error("real_notes_cancellation_finish_invalid");
    record.finishing = true;
    try { await fulfill(); if (this.#closed || this.#failed) throw Error("real_notes_cancellation_closed"); record.settled = true; this.#fulfilled++; return Object.freeze({ kind: "fulfilled" }); }
    catch (error) {
      let known = false;
      try {
        const diagnostic = own(error, "browserDiagnostic");
        known = own(error, "canceled") === true && own(error, "protocolReason") === "request_no_longer_exists"
          && own(diagnostic, "method") === "Fetch.fulfillRequest" && own(diagnostic, "protocol_reason") === "request_no_longer_exists";
      } catch { /* Missing/accessor/unknown diagnostic is not cancellation proof. */ }
      if (!this.#closed && !this.#failed && known && record.canceled && this.#networks.get(record.networkId) === record && this.#fetches.has(record.fetchId)) {
        record.settled = true; this.#canceled++; return Object.freeze({ kind: "verified_browser_canceled" });
      }
      this.#failed = true; throw Error("real_notes_fulfill_failed");
    }
  }
  snapshot() { return { registered: this.#registered, fulfilled: this.#fulfilled, verified_canceled: this.#canceled, pending: this.#registered - this.#fulfilled - this.#canceled, failed: this.#failed, closed: this.#closed }; }
  close() { if (this.#registered !== this.#fulfilled + this.#canceled) this.#failed = true; this.#closed = true; }
}

// One already-computed real response at a time. The four-second lease includes
// the finish callback; attempted, abandoned and completed releases are distinct.
export class NotesResponseGate {
  #origin; #now; #set; #clear; #last = -1; #timer = null; #armed = null; #slot = null; #closed = false;
  #failure = null; #captured = 0; #released = 0; #abandoned = 0; #fulfilled = 0; #canceled = 0;
  constructor({ origin, now = () => performance.now(), setTimer = setTimeout, clearTimer = clearTimeout }) {
    this.#origin = loopback(origin);
    if ([now, setTimer, clearTimer].some(value => typeof value !== "function")) throw Error("real_notes_gate_clock_invalid");
    this.#now = now; this.#set = setTimer; this.#clear = clearTimer;
  }
  #tick() {
    const value = this.#now();
    if (typeof value !== "number" || !Number.isFinite(value) || value < 0 || value < this.#last) throw Error("real_notes_gate_clock_invalid");
    this.#last = value; return value;
  }
  #fail(reason) {
    this.#failure ||= reason;
    if (this.#timer !== null) { this.#clear(this.#timer); this.#timer = null; }
    if (this.#slot || this.#armed) this.#abandoned++;
    const reject = this.#slot?.reject;
    this.#slot = null; this.#armed = null;
    reject?.(Error(this.#failure));
  }
  assertHealthy() { if (this.#failure) throw Error(this.#failure); if (this.#closed) throw Error("real_notes_gate_closed"); }
  arm(id, revision) {
    this.assertHealthy();
    try { this.#tick(); } catch { this.#fail("real_notes_gate_clock_invalid"); throw Error(this.#failure); }
    if (typeof id !== "string" || !uuid.test(id) || !positive(revision)) throw Error("real_notes_hold_source_invalid");
    if (this.#slot || this.#armed || this.#captured >= 4) throw Error("real_notes_hold_capacity");
    this.#armed = { id, revision };
  }
  capture(request, response, finish) {
    this.assertHealthy(); if (!this.#armed) return false;
    try {
      if (own(request, "method") !== "POST") return false;
      const rawUrl = own(request, "url"); if (typeof rawUrl !== "string") throw Error();
      const url = new URL(rawUrl), match = /^\/api\/v1\/me\/context-notes\/([a-f0-9-]{36})\/prepare$/.exec(url.pathname);
      if (!match) return false;
      const encoded = own(response, "bodyBase64"), raw = own(request, "postData");
      if (rawUrl !== this.#origin + url.pathname || url.origin !== this.#origin || url.username || url.password || url.hash || url.search || !uuid.test(match[1]) || match[1] !== this.#armed.id
        || own(response, "status") !== 200 || typeof finish !== "function" || typeof raw !== "string" || Buffer.byteLength(raw) > 8192
        || typeof encoded !== "string" || encoded.length > 21848 || !/^[A-Za-z0-9+/]*={0,2}$/.test(encoded)
        || Buffer.from(encoded, "base64").length > 16384 || Buffer.from(encoded, "base64").toString("base64") !== encoded) throw Error();
      const input = JSON.parse(raw), output = JSON.parse(new TextDecoder("utf-8", { fatal: true }).decode(Buffer.from(encoded, "base64")));
      if (!exact(input, ["schemaVersion", "expected_scope_id", "revision"]) || input.schemaVersion !== 1 || typeof input.expected_scope_id !== "string" || !hex.test(input.expected_scope_id)
        || input.revision !== this.#armed.revision || !exact(output, ["schemaVersion", "owner_id", "scope", "unverified", "execution_enabled", "source", "draft", "requires_review"])
        || output.schemaVersion !== 1 || output.unverified !== true || output.execution_enabled !== false || output.requires_review !== true
        || typeof output.owner_id !== "string" || !uuid.test(output.owner_id) || !exact(output.scope, ["id", "can_use"]) || output.scope.id !== input.expected_scope_id || output.scope.can_use !== true
        || !exact(output.source, ["id", "revision", "kind", "label"]) || output.source.id !== match[1] || output.source.revision !== this.#armed.revision
        || !["note", "metric_definition"].includes(output.source.kind) || typeof output.source.label !== "string" || typeof output.draft !== "string") throw Error();
      const started = this.#tick(); this.#slot = { finish, started, until: started + 4000, reject: null }; this.#armed = null; this.#captured++;
      this.#timer = this.#set(() => this.#fail("real_notes_held_response_deadline"), 4000);
      return true;
    } catch (error) {
      this.#fail(error.message === "real_notes_gate_clock_invalid" ? error.message : "real_notes_hold_response_invalid"); throw Error(this.#failure);
    }
  }
  async release() {
    this.assertHealthy(); const slot = this.#slot; if (!slot) throw Error("real_notes_hold_missing");
    try {
      if (this.#tick() >= slot.until) throw Error("real_notes_held_response_deadline");
      const lease = new Promise((_, reject) => { slot.reject = reject; });
      const outcome = await Promise.race([Promise.resolve().then(slot.finish), lease]);
      this.assertHealthy(); if (this.#tick() >= slot.until || this.#slot !== slot) throw Error("real_notes_held_response_deadline");
      if (!exact(outcome, ["kind"]) || !["fulfilled", "verified_browser_canceled"].includes(outcome.kind)) throw Error("real_notes_finish_outcome_invalid");
      this.#clear(this.#timer); this.#timer = null; this.#slot = null; this.#released++;
      if (outcome.kind === "fulfilled") this.#fulfilled++; else this.#canceled++;
      return outcome.kind;
    } catch (error) { this.#fail(error.message === "real_notes_gate_clock_invalid" ? error.message : "real_notes_release_failed"); throw Error(this.#failure); }
  }
  snapshot() { return { captured: this.#captured, released: this.#released, fulfilled: this.#fulfilled, verified_canceled: this.#canceled, remaining: this.#slot ? 1 : 0, armed: this.#armed !== null, abandoned: this.#abandoned, failed: this.#failure !== null, closed: this.#closed }; }
  close() { if (this.#slot || this.#armed) this.#fail("real_notes_hold_abandoned"); if (this.#timer !== null) this.#clear(this.#timer); this.#timer = null; this.#closed = true; }
}

export async function runRealContextNotesChecks(ctx) {
  const { check, click, fill, evaluate, waitFor, rawRequest, screenshot, session, gate, send, control, outcomes, logout } = ctx;
  const root = "/api/v1/me/context-notes", quote = JSON.stringify, gold = REAL_NOTES_GOLD, key = value => notesRealKey(send, value);
  let currentSession = session, history = null, caseIndex = 0;
  const stats = [], delayedResponses = [];
  const headers = (revision = history, csrf = currentSession.csrf_token) => ({ "X-CSRF-Token": csrf, ...(revision ? { "X-Aqua-History-Revision": revision } : {}) });
  const req = async (method, path, body = null, custom = headers()) => {
    const value = await rawRequest(method, path, body, custom); assert.notEqual(value.status, 429, "real_notes_unexpected_admission_denial"); return value;
  };
  const json = value => { assert.equal(typeof value.body, "string"); return JSON.parse(value.body); };
  const list = async () => { const response = await req("GET", root); assert.equal(response.status, 200); return decodeNoteList(json(response), currentSession.user.id); };
  const record = async expression => { await check(`notes ${String(++caseIndex).padStart(2, "0")}: ${REAL_NOTES_CASES[caseIndex - 1]}`, expression); };
  const snapshot = async () => { const value = notesStats(await control("notes_stats")); stats.push(value); return value; };
  const refresh = async () => {
    const response = await req("GET", "/api/auth/me"); assert.equal(response.status, 200); currentSession = json(response);
    assert.ok(typeof response.history_revision === "string" && hex.test(response.history_revision)); history = response.history_revision;
    await evaluate("(()=>{const channel=new BroadcastChannel('aqua-session-events');channel.postMessage({type:'changed'});channel.close();return true})()");
    await waitFor(`Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&!document.querySelector('dialog[open]')&&document.querySelector('.opal-composer textarea').disabled===${quote(!currentSession.can_query)}`, "real_notes_session_refresh");
  };
  const open = async () => { await click("[data-open-companion]"); await waitFor("Boolean(document.querySelector('[data-notes-open]'))", "real_notes_area"); await click("[data-notes-open]"); await waitFor("Boolean(document.querySelector('[data-notes-new]'))", "real_notes_library"); };
  const close = async () => { await key("Escape"); await waitFor("!document.querySelector('dialog[open]')", "real_notes_closed"); };
  const select = async id => { await click(`[data-notes-select="${id}"]`); await waitFor("Boolean(document.querySelector('[data-notes-body]'))", "real_notes_body"); };
  const prepare = async () => { await click("[data-notes-prepare]"); await waitFor("Boolean(document.querySelector('[data-notes-preview]'))", "real_notes_prepared"); };
  const held = async () => { const stop = performance.now() + 3500; while (gate.snapshot().remaining !== 1 && performance.now() < stop) { gate.assertHealthy(); await new Promise(resolve => setTimeout(resolve, 10)); } assert.equal(gate.snapshot().remaining, 1, "real_notes_computed_response_held"); };
  const nativeTo = async selector => {
    for (let i = 0; i < 40; i++) { if (await evaluate(`document.activeElement===document.querySelector(${quote(selector)})`)) return; await key("Tab"); }
    throw Error("real_notes_native_control_unreachable");
  };
  const newNote = async () => {
    await nativeTo("[data-notes-new]"); await key("Enter"); await waitFor("Boolean(document.querySelector('[data-notes-body]'))", "real_notes_new_editor");
    await nativeTo("[data-notes-label]"); await fill("[data-notes-label]", gold.label);
    await nativeTo("[data-notes-body]"); await fill("[data-notes-body]", gold.body);
    await nativeTo("[data-notes-save]"); await key("Enter"); await waitFor("document.querySelector('.context-notes [role=status]')?.textContent.includes('Saved your note')", "real_notes_created");
  };
  const forget = async id => {
    await click("[data-notes-forget]");
    assert.equal(await evaluate("Boolean(document.querySelector('[data-notes-forget-confirm]'))"), true);
    await click("[data-notes-forget-confirm]");
    await waitFor(`(${notesForgetConfirmed})(document.querySelector('[data-context-notes]'), ${quote(id)})`, "real_notes_forgotten");
  };
  const prepBody = (scope, revision) => ({ schemaVersion: 1, expected_scope_id: scope.id, revision });

  const before = await snapshot(); assert.equal(before.notes, 0);
  const initial = await req("GET", root); assert.equal(initial.status, 200);
  const initialList = decodeNoteList(json(initial), session.user.id); assert.equal(initialList.scope.can_use, false); assert.deepEqual(initialList.items, []);
  await evaluate("window.__realNotesComposer=document.querySelector('.opal-composer textarea');window.__realNotesDraft=window.__realNotesComposer.value;true");
  await open();
  assert.ok(outcomes().some(call => call.path === root && call.method === "GET" && call.private_no_store === true));
  await record("document.querySelector('[data-notes-new]').disabled&&!document.querySelector('[data-notes-body],[data-notes-prepare]')&&window.__realNotesComposer.value===window.__realNotesDraft");
  await close(); await control("notes_grant"); await refresh(); assert.equal(currentSession.can_query, true); await open();
  const helpCalls = outcomes().filter(call => call.path === "/api/v1/companion/capabilities"); assert.ok(helpCalls.length > 0 && helpCalls.every(call => call.status === 404));
  await record("!document.querySelector('[data-notes-new]').disabled&&!document.querySelector('[data-notes-body]')");
  await newNote(); let library = await list(), meta = library.items[0]; assert.equal(library.items.length, 1); assert.equal(meta.revision, 1);
  let note = decodeNote(json(await req("GET", `${root}/${meta.id}`)), currentSession.user.id, library.scope, meta).note;
  assert.equal(note.kind, gold.kind); assert.equal(note.label, gold.label); assert.equal(note.body, gold.body);
  assert.ok(outcomes().some(call => call.path === root && call.method === "POST" && call.status === 201));
  await record(`document.querySelector('[data-notes-body]').value===${quote(gold.body)}&&document.querySelector('[data-notes-label]').labels.length===1&&document.querySelector('[data-notes-body]').labels.length===1`);
  assert.ok(library.items.every(item => !Object.hasOwn(item, "body")));
  await record(`document.querySelector('[data-notes-body]').value===${quote(gold.body)}`);
  await record("!document.querySelector('.context-notes metric,.context-notes script,.context-notes iframe')&&document.querySelector('[data-notes-body]').value.includes('<metric>')");
  await prepare(); const afterPrepare = await snapshot(); assert.equal(afterPrepare.notes, 1);
  await record(`document.querySelector('[data-notes-draft]').value===${quote(gold.body)}&&document.querySelector('[data-notes-preview]').textContent.includes('revision 1')&&window.__realNotesComposer.value===window.__realNotesDraft`);
  const edited = gold.body + gold.draftSuffix; await fill("[data-notes-draft]", edited); await nativeTo("[data-notes-apply]"); await key("Enter");
  await waitFor("!document.querySelector('dialog[open]')", "real_notes_applied");
  await record(`window.__realNotesComposer.value===${quote(edited)}&&document.querySelector('.opal-composer textarea')===window.__realNotesComposer`);
  note = decodeNote(json(await req("GET", `${root}/${meta.id}`)), currentSession.user.id, library.scope, meta).note; assert.equal(note.body, gold.body);
  await open(); await select(meta.id); await record(`document.querySelector('[data-notes-body]').value===${quote(gold.body)}&&!document.querySelector('[data-notes-preview]')`);
  await fill("[data-notes-label]", gold.correctedLabel); await fill("[data-notes-body]", gold.correctedBody);
  await evaluate("(()=>{const el=document.querySelector('[data-notes-kind]');el.value='metric_definition';el.dispatchEvent(new Event('change',{bubbles:true}));return true})()");
  await click("[data-notes-save]"); await waitFor("document.querySelector('.context-notes [role=status]')?.textContent.includes('Saved your correction')", "real_notes_corrected");
  const old = await req("POST", `${root}/${meta.id}/prepare`, prepBody(library.scope, 1)); assert.equal(old.status, 409);
  library = await list(); meta = library.items[0]; assert.equal(meta.revision, 2);
  note = decodeNote(json(await req("GET", `${root}/${meta.id}`)), currentSession.user.id, library.scope, meta).note;
  assert.equal(note.kind, gold.correctedKind); assert.equal(note.label, gold.correctedLabel); assert.equal(note.body, gold.correctedBody);
  const prepared = await req("POST", `${root}/${meta.id}/prepare`, prepBody(library.scope, 2)); assert.equal(prepared.status, 200);
  decodePreparedNote(json(prepared), currentSession.user.id, library.scope, note);
  await record(`document.querySelector('[data-notes-body]').value===${quote(gold.correctedBody)}`);
  const create = { schemaVersion: 1, client_request_id: "57000000-0000-4000-8000-000000000001", expected_scope_id: library.scope.id, kind: gold.kind, label: gold.label, body: gold.body };
  const badScope = await req("POST", root, { ...create, expected_scope_id: "0".repeat(64) }); assert.equal(badScope.status, 409);
  const authority = await req("POST", root, { ...create, owner_id: "57000000-0000-4000-8000-000000000099" }); assert.equal(authority.status, 422);
  const noCsrf = await req("POST", root, create, history ? { "X-Aqua-History-Revision": history } : {}); assert.equal(noCsrf.status, 403);
  for (const result of [badScope, authority, noCsrf]) assert.ok(!result.body.includes(gold.body));
  await record(`document.querySelector('[data-notes-body]').value===${quote(gold.correctedBody)}&&window.__realNotesComposer.value===${quote(edited)}`);
  const forgottenId = meta.id; await forget(forgottenId); assert.equal((await req("GET", `${root}/${forgottenId}`)).status, 404); assert.equal((await list()).items.length, 0);
  await record("!document.querySelector('[data-notes-body],[data-notes-preview]')");
  await newNote(); library = await list(); meta = library.items[0]; assert.equal(library.items.length, 1); note = decodeNote(json(await req("GET", `${root}/${meta.id}`)), currentSession.user.id, library.scope, meta).note;
  assert.equal(note.body, gold.body); await record(`document.querySelector('[data-notes-body]').value===${quote(gold.body)}`);
  gate.arm(meta.id, meta.revision); await click("[data-notes-prepare]"); await held(); await close(); delayedResponses.push({ case: 13, outcome: await gate.release() }); await open();
  await record("!document.querySelector('[data-notes-body],[data-notes-preview]')");
  await select(meta.id); gate.arm(meta.id, meta.revision); await click("[data-notes-prepare]"); await held();
  // Supplemental controlled input events represent another view editing a draft;
  // native dialog keyboard evidence is recorded separately, never inferred here.
  await fill(".opal-composer textarea", gold.newerDraft); delayedResponses.push({ case: 14, outcome: await gate.release() }); await waitFor("Boolean(document.querySelector('[data-notes-preview]'))", "real_notes_held_draft_preview");
  await click("[data-notes-apply]"); await waitFor("document.querySelector('.context-notes [role=alert]')?.textContent.includes('composer changed')", "real_notes_newer_draft_fenced");
  await record(`window.__realNotesComposer.value===${quote(gold.newerDraft)}`); await close();
  await control("notes_revoke"); await refresh(); library = await list(); assert.equal(library.scope.can_use, false);
  const unavailable = library.items[0]; assert.equal(unavailable.availability, "unavailable"); assert.equal(unavailable.label, "Unavailable saved context");
  for (const value of [unavailable.kind, unavailable.created_at, unavailable.updated_at]) assert.equal(value, null);
  assert.ok([403, 404].includes((await req("GET", `${root}/${meta.id}`)).status)); assert.ok([403, 404].includes((await req("POST", `${root}/${meta.id}/prepare`, prepBody(library.scope, meta.revision))).status));
  await open(); await record("document.querySelector('.context-notes').textContent.includes('Unavailable saved context')&&!document.querySelector('[data-notes-body],[data-notes-preview]')"); await close();
  const oldScope = library.scope; await control("notes_regrant"); await refresh(); library = await list(); assert.equal(library.scope.can_use, true);
  assert.notEqual(library.scope.id, oldScope.id); assert.equal(library.items[0].availability, "unavailable"); assert.equal((await req("POST", root, { ...create, expected_scope_id: oldScope.id })).status, 409);
  await open(); await click(`[data-notes-select="${meta.id}"]`);
  await record("!document.querySelector('[data-notes-body],[data-notes-prepare]')&&Boolean(document.querySelector('[data-notes-forget]'))");
  await forget(meta.id); await newNote(); library = await list(); meta = library.items[0]; assert.equal(library.items.length, 1); const currentScope = library.scope;
  await record(`document.querySelector('[data-notes-body]').value===${quote(gold.body)}`);
  gate.arm(meta.id, meta.revision); await click("[data-notes-prepare]"); await held(); const oldHistory = history; await control("notes_history_advance"); await refresh(); assert.notEqual(history, oldHistory); delayedResponses.push({ case: 18, outcome: await gate.release() });
  assert.equal((await req("GET", root, null, headers(oldHistory))).status, 409);
  assert.equal((await req("POST", `${root}/${meta.id}/prepare`, prepBody(currentScope, meta.revision), headers(oldHistory))).status, 409);
  library = await list(); assert.equal(library.items[0].availability, "available"); assert.notEqual(library.scope.id, currentScope.id);
  await open(); await record("!document.querySelector('[data-notes-body],[data-notes-preview]')");
  await select(meta.id); gate.arm(meta.id, meta.revision); await click("[data-notes-prepare]"); await held();
  assert.equal((await req("POST", "/api/auth/logout", {}, headers())).status, 204);
  const configResponse = await req("GET", "/api/auth/config"); assert.equal(configResponse.status, 200); const config = json(configResponse);
  assert.equal((await req("POST", "/api/auth/google", { credential: JSON.stringify({ nonce: config.nonce }) }, { "X-CSRF-Token": config.csrf_token })).status, 200);
  const firstOwner = currentSession.user.id; await refresh(); assert.notEqual(currentSession.user.id, firstOwner); assert.equal(currentSession.can_query, false); delayedResponses.push({ case: 19, outcome: await gate.release() });
  await open(); await record("!document.querySelector('[data-notes-body],[data-notes-preview]')&&document.querySelector('.context-notes').textContent.includes('No notes saved yet')");
  library = await list(); assert.equal(library.items.length, 0);
  for (const [method, path, body, status] of [["GET", `${root}/${meta.id}`, null, 403], ["POST", `${root}/${meta.id}/prepare`, prepBody(library.scope, meta.revision), 403], ["POST", `${root}/${meta.id}/forget`, prepBody(library.scope, meta.revision), 404]]) {
    const result = await req(method, path, body); assert.equal(result.status, status); assert.ok(!result.body.includes(gold.body));
  }
  await record("!document.querySelector('[data-notes-body],[data-notes-preview]')");
  await send("Emulation.setDeviceMetricsOverride", { width: 320, height: 844, deviceScaleFactor: 1, mobile: true });
  const normal = await evaluate("parseFloat(getComputedStyle(document.querySelector('.context-notes > p')).fontSize)");
  await evaluate("document.querySelector('.opal-workspace').style.setProperty('--pref-text-scale','2');true");
  const large = await evaluate("parseFloat(getComputedStyle(document.querySelector('.context-notes > p')).fontSize)"); assert.ok(normal >= 14 && Math.abs(large - normal * 2) <= 0.1);
  await evaluate("document.querySelector('[data-close-companion]').focus();true"); await key("Tab"); await nativeTo("[data-close-companion]");
  await screenshot("real-notes-320-double-text-keyboard-close");
  await record("(()=>{const d=document.querySelector('dialog[open]'),r=d.getBoundingClientRect();return document.activeElement===document.querySelector('[data-close-companion]')&&r.left>=-1&&r.right<=innerWidth+1&&d.scrollWidth<=d.clientWidth+1&&[...d.querySelectorAll('button:not(:disabled),input,select,textarea')].every(el=>el.getBoundingClientRect().height>=43.5)})()");
  await close(); const finalStats = await snapshot(); assert.equal(finalStats.notes, 1);
  const writeOutcomes = outcomes().filter(call => call.method !== "GET" && (call.path === "/api/query" || /\/analysis-requests(?:\/|$)/.test(call.path) || /^\/api\/v1\/chats(?:\/|$)/.test(call.path)));
  assert.equal(writeOutcomes.length, 0); assert.equal(gate.snapshot().captured, 4); assert.equal(gate.snapshot().released, 4); assert.equal(gate.snapshot().remaining, 0); gate.assertHealthy();
  await logout(); assert.equal((await req("GET", "/api/auth/me")).status, 401);
  await record(`(()=>{const values=[location.href,document.documentElement.outerHTML,...Object.values(localStorage),...Object.values(sessionStorage)];return !values.some(value=>[${quote(gold.body)},${quote(gold.correctedBody)}].some(text=>value.includes(text)))})()`);
  assert.equal(caseIndex, 22); const noteCalls = outcomes().filter(call => call.path === root || call.path.startsWith(root + "/")); assert.ok(noteCalls.length < 60);
  assert.ok(noteCalls.every(call => call.private_no_store === true));
  return { transport: "real_fastapi_testclient_disposable_postgres_jsonl", cases: [...REAL_NOTES_CASES], notes_requests: noteCalls.length,
    stats, analytical_submissions: writeOutcomes.length, engine_calls: finalStats.engine_calls, enqueue_calls: finalStats.enqueue_calls,
    provider_calls: finalStats.provider_calls, response_hold: gate.snapshot(), delayed_responses: delayedResponses,
    response_claim: "fulfilled_and_verified_canceled_undelivered_outcomes_are_distinct",
    owner_boundary: "actual_cookie_logout_google_login_and_modeled_cross_tab_signal", history_boundary: "actual_history_generation_and_modeled_existing_cross_tab_signal",
    late_composer_edit: "supplemental_controlled_input_events", native_keyboard: true, bank_connected: false };
}
