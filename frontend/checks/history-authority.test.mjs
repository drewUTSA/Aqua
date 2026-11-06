import assert from 'node:assert/strict';
import test, { beforeEach } from 'node:test';
import { activateSession, assertHistory, bindHistoryIntent, captureHistory, clearHistory, deletionHistory, HISTORY_HEADER, historyHeaders, observeHistory, stampSession, subscribeHistory } from '../src/services/historyAuthority.js';
import { fetchSession } from '../src/services/authClient.js';
import { workspaceRequest, submitQuestion } from '../src/services/workspaceClient.js';
import { queryApi } from '../src/services/apiClient.js';
import { watchAnalysis } from '../src/services/analysisClient.js';
import { observeAnalysis } from '../src/services/analysisObserver.js';
const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', other = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb';
const old = 'f'.repeat(64), fresh = '0'.repeat(64);
const response = (body, revision = old, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json', [HISTORY_HEADER]: revision } });
function session(revision = old, id = owner, csrf = 'csrf') {
  const value = { user: { id, email: 'synthetic@example.test', name: '', picture: '' }, csrf_token: csrf, can_query: true };
  return stampSession(value, response({}, revision), captureHistory());
}
beforeEach(() => clearHistory());

test('auth header metadata preserves the session DTO and installs only an explicitly current session', async t => {
  const body = { user: { id: owner, email: '', name: '', picture: '' }, csrf_token: 'csrf', can_query: true };
  t.mock.method(globalThis, 'fetch', async () => response(body));
  const result = await fetchSession();
  assert.deepEqual(result, body); assert.equal(captureHistory().owner, null);
  activateSession(result); assert.equal(captureHistory().revision, old);
  assert.deepEqual(Object.keys(result), ['user', 'csrf_token', 'can_query']);
});
test('opaque revisions may change in either lexical direction, while held intents and stale auth cannot be upgraded', () => {
  activateSession(session()); const original = captureHistory();
  const intent = {}; bindHistoryIntent(intent, original); const delayed = session();
  assert.throws(() => observeHistory(response({}, fresh), original), { code: 'history_changed' });
  assert.equal(captureHistory().revision, fresh);
  assert.throws(() => bindHistoryIntent(intent, captureHistory()), { name: 'AbortError' });
  assert.throws(() => activateSession(delayed), { name: 'AbortError' });
  const current = captureHistory(); assert.deepEqual(historyHeaders(current), { [HISTORY_HEADER]: fresh });
  assert.throws(() => observeHistory(response({}, old), original), { name: 'AbortError' });
  assert.equal(captureHistory().revision, fresh);
  activateSession(session(fresh)); assertHistory(current);
});
test('owner and CSRF replacement permanently retire old captures, including A to B to A', () => {
  activateSession(session()); const first = captureHistory();
  activateSession(session(old, other, 'other-csrf'));
  activateSession(session(old));
  assert.throws(() => assertHistory(first), { name: 'AbortError' });
  assert.throws(() => captureHistory('other-csrf'), { name: 'AbortError' });
  assert.equal(deletionHistory(first, fresh), false); assert.equal(captureHistory().revision, old);
});
test('history change emits a single metadata signal and suppresses a changed response body', async t => {
  activateSession(session()); const events = [], stop = subscribeHistory(value => events.push(value.sequence));
  let calls = 0; t.mock.method(globalThis, 'fetch', async (_, options) => {
    calls++; assert.equal(options.headers[HISTORY_HEADER], calls === 1 ? old : fresh); return response({ safe: true }, fresh);
  });
  try { await assert.rejects(workspaceRequest('/chats'), { code: 'history_changed' });
    assert.deepEqual(await workspaceRequest('/chats'), { safe: true });
    assert.equal(events.length, 1);
  } finally { stop(); }
});
test('an ordinary CAS conflict preserves the current workspace, while a generation conflict retires it', async t => {
  activateSession(session()); const first = captureHistory();
  const mock = t.mock.method(globalThis, 'fetch', async () => response({}, old, 409));
  await assert.rejects(workspaceRequest('/chats'), { code: 'conflict' }); assertHistory(first);
  mock.mock.mockImplementation(async () => response({}, fresh, 409));
  await assert.rejects(workspaceRequest('/chats'), { code: 'history_changed' });
  assert.throws(() => assertHistory(first), { name: 'AbortError' });
});
test('held submission retries fail before fetch, and a fresh intent still reaches the fixed route', async t => {
  activateSession(session()); const body = { client_request_id: crypto.randomUUID(), question: 'synthetic' };
  bindHistoryIntent(body); const initial = captureHistory(); deletionHistory(initial, fresh);
  const mock = t.mock.method(globalThis, 'fetch', async () => response({}, fresh, 503));
  assert.throws(() => submitQuestion(body, { csrfToken: 'csrf' }), { name: 'AbortError' });
  assert.equal(mock.mock.calls.length, 0);
  await assert.rejects(submitQuestion({ ...body, client_request_id: crypto.randomUUID() }, { csrfToken: 'csrf' }), { code: 'unavailable' });
  assert.equal(mock.mock.calls.length, 1);
});
test('a body read started before deletion cannot publish after the authority changed', async t => {
  activateSession(session()); let release, began;
  const reading = new Promise(resolve => began = resolve);
  const reader = { read: () => { began(); return new Promise(resolve => release = resolve); }, cancel: async () => {}, releaseLock() {} };
  t.mock.method(globalThis, 'fetch', async () => ({ ok: true, status: 200, redirected: false, headers: response({}).headers, body: { getReader: () => reader } }));
  const pending = workspaceRequest('/chats'); await reading;
  deletionHistory(captureHistory(), fresh); release({ done: true });
  await assert.rejects(pending, { name: 'AbortError' });
});
test('legacy query uses the captured revision and a late answer is discarded instead of retried', async t => {
  activateSession(session()); let release, began; const reading = new Promise(resolve => began = resolve);
  t.mock.method(globalThis, 'fetch', async (_, options) => {
    assert.equal(options.headers[HISTORY_HEADER], old);
    return { ok: true, status: 200, headers: response({}).headers, json: async () => { began(); await new Promise(resolve => release = resolve); return { status: 'success', message: 'old private output', tables: [], kpis: [], visualizations: [] }; } };
  });
  const pending = queryApi({ prompt: 'synthetic', csrfToken: 'csrf' }); await reading;
  deletionHistory(captureHistory(), fresh); release(); await assert.rejects(pending, { name: 'AbortError' });
});
test('a held SSE chunk cannot emit metadata after history reset', async t => {
  activateSession(session()); let release, began, emitted = 0; const reading = new Promise(resolve => began = resolve);
  const headers = new Headers({ [HISTORY_HEADER]: old, 'Content-Type': 'text/event-stream' });
  t.mock.method(globalThis, 'fetch', async () => ({ ok: true, status: 200, redirected: false, headers, body: { getReader: () => ({ read: () => { began(); return new Promise(resolve => release = resolve); }, cancel: async () => {}, releaseLock() {} }) } }));
  const pending = watchAnalysis(owner, { onEvent: () => emitted++ }); await reading;
  deletionHistory(captureHistory(), fresh); release({ done: false, value: new TextEncoder().encode('data: {}\n\n') });
  await assert.rejects(pending, { name: 'AbortError' }); assert.equal(emitted, 0);
});
test('observer never opens a replacement stream after a held snapshot loses its context', async () => {
  activateSession(session()); let reads = 0, streams = 0;
  await assert.rejects(observeAnalysis(owner, { signal: new AbortController().signal, onConnection() {}, onSnapshot() {}, onProgress() {},
    read: async () => { reads++; deletionHistory(captureHistory(), fresh); return {}; }, watch: async () => { streams++; } }), { name: 'AbortError' });
  assert.equal(reads, 1); assert.equal(streams, 0);
});
test('missing or malformed authenticated revision fails closed without accepting data', () => {
  for (const value of [null, 'authority-from-body', 'A'.repeat(64)]) {
    clearHistory(); activateSession(session()); const before = captureHistory();
    const headers = new Headers(); if (value !== null) headers.set(HISTORY_HEADER, value);
    assert.throws(() => observeHistory({ ok: true, headers }, before), { code: 'history_changed' });
    assert.throws(() => assertHistory(before), { name: 'AbortError' });
  }
});
