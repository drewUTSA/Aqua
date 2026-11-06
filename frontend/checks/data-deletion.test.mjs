import assert from 'node:assert/strict';
import test, { beforeEach } from 'node:test';
import { actionTarget } from '../src/settings/accountSecurityContract.js';
import { actionKey, canAccountAction, createActionProofVault } from '../src/settings/accountSecurityState.js';
import { DELETION_SCOPES, deletionReply, deletionStart } from '../src/settings/dataDeletionContract.js';
import { createDeletionReceipt, deletionReducer, initialDeletion } from '../src/settings/dataDeletionState.js';
import { reconcileDataDeletion, startDataDeletion } from '../src/settings/dataDeletionClient.js';
import { activateSession, captureHistory, clearHistory, deletionHistory, HISTORY_HEADER, stampSession, subscribeHistory } from '../src/services/historyAuthority.js';
const owner = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa', other = 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', job = 'cccccccc-cccc-4ccc-8ccc-cccccccccccc';
const proof = 'v2.' + 'p'.repeat(43), revision = '1'.repeat(64), csrf = 'synthetic-csrf';
const json = (value, status = 200) => new Response(JSON.stringify(value), { status, headers: { 'Content-Type': 'application/json' } });
function activate() { activateSession(stampSession({ user: { id: owner }, csrf_token: csrf }, new Response(null, { headers: { [HISTORY_HEADER]: revision } }), captureHistory())); }
function receipt(scope = 'chat_history_v1', now) { return createDeletionReceipt(owner, csrf, scope, now); }
function reply(value, state = 'accepted') {
  const now = Date.now(), created = new Date(now - 1000), expires = new Date(now + 599000);
  return { schemaVersion: 1, user_id: owner, job: { id: job, intent_id: value.intent, scope: value.scope, state, accepted: state !== 'awaiting_authority', cleanup_complete: state === 'complete', created_at: created.toISOString(), receipt_expires_at: expires.toISOString() }, history_revision: '2'.repeat(64) };
}
beforeEach(() => { clearHistory(); activate(); });

for (const scope of Object.keys(DELETION_SCOPES)) test(scope + ' binds proof target, fixed scope and literal confirmation to the exact intent', () => {
  const value = receipt(scope), operation = DELETION_SCOPES[scope].operation;
  assert.deepEqual(actionTarget({ operation, target_intent_id: value.intent }), { operation, target_intent_id: value.intent });
  assert.equal(actionKey({ operation, intentId: value.intent }), operation + ':' + value.intent);
  assert.throws(() => actionTarget({ operation, target_session_id: value.intent }));
  assert.throws(() => actionTarget({ operation, target_intent_id: value.intent.toUpperCase() }));
  const body = { intent_id: value.intent, scope, confirmation: DELETION_SCOPES[scope].confirmation, proof_token: proof, receipt_token: value.token() };
  assert.deepEqual(deletionStart(body), body);
  for (const patch of [{ confirmation: 'delete account' }, { scope: 'all' }, { owner }, { receipt_token: proof }, { privacy_epoch: 1 }]) assert.throws(() => deletionStart({ ...body, ...patch }));
  assert.equal(canAccountAction({ profile: {}, methods: { capabilities: { recent_proof: true }, password: { linked: true, available: true } } }, { operation, intentId: value.intent }), false);
});
test('deletion proof vault permits only its owner, CSRF, intent and live authority generation', () => {
  const value = receipt(), action = { operation: 'history_delete', intentId: value.intent };
  const identity = { owner, csrfToken: csrf, active: true, generation: 1 }, vault = createActionProofVault(owner, action, () => identity);
  const issued = { proof_token: proof, expires_at: new Date(Date.now() + 200000).toISOString() };
  assert.equal(vault.store(issued), true); assert.equal(vault.peek(action), proof);
  identity.generation++; assert.equal(vault.peek(action), null);
  assert.equal(vault.store(issued), true); assert.equal(vault.take(action), proof); assert.equal(vault.take(action), null);
  vault.store(issued); assert.equal(vault.take({ ...action, intentId: other }), null);
});
test('receipt exists before mutation, expires within ten minutes and cannot revive after close or a new login', () => {
  assert.throws(() => createDeletionReceipt(other, csrf, 'account_v1'));
  let now = Date.now(); const value = receipt('account_v1', () => now), first = value.token();
  assert.equal(Object.isFrozen(value), true);
  assert.match(first, /^v2\.[A-Za-z0-9_-]{43}$/); assert.equal(value.attempted(), false);
  assert.equal(value.matches({ user: null }), false); assert.equal(value.attempt(), true); assert.equal(value.attempt(), false);
  assert.equal(value.matches({ user: null }), true);
  assert.equal(value.matches({ user: { id: owner }, csrfToken: csrf }), true);
  assert.equal(value.matches({ user: { id: owner }, csrfToken: 'new-csrf' }), false);
  assert.equal(value.matches({ user: { id: other }, csrfToken: csrf }), false);
  now += 600000; assert.equal(value.current(), false); assert.throws(() => value.token());
  const closed = receipt(); closed.clear(); assert.equal(closed.current(), false); assert.throws(() => closed.token());
});
test('server expiry can shorten a receipt but later status cannot extend or replace its job binding', () => {
  let now = Date.now(); const value = receipt('chat_history_v1', () => now), first = reply(value);
  first.job.receipt_expires_at = new Date(now + 60000).toISOString();
  assert.equal(value.accept(first), true); assert.equal(value.deadline(), now + 60000);
  const later = reply(value); assert.equal(value.accept(later), true); assert.equal(value.deadline(), now + 60000);
  assert.throws(() => deletionReply({ ...later, job: { ...later.job, id: other } }, value.context(), 200));
  now += 60000; assert.equal(value.current(), false);
});
test('accepted and complete receipt reads publish history once without repeated refresh or remount signals', () => {
  const value = receipt(), next = 'f'.repeat(64); let refreshes = 0;
  const stop = subscribeHistory(() => refreshes++);
  try {
    assert.equal(value.applyHistoryRevision(next), true);
    const context = captureHistory(), epoch = context.sequence;
    for (const state of ['accepted', 'purging', 'complete']) {
      const metadata = reply(value, state); metadata.history_revision = next;
      value.accept(metadata);
      assert.equal(value.applyHistoryRevision(metadata.history_revision), false);
      assert.equal(captureHistory(), context); assert.equal(captureHistory().sequence, epoch);
    }
    assert.equal(refreshes, 1);
  } finally { stop(); }
});
test('an old receipt cannot publish or refresh after same-owner authority advancement or owner/CSRF replacement', () => {
  for (const change of ['revision', 'owner', 'csrf', 'owner-roundtrip']) {
    clearHistory(); activate(); const value = receipt(); let refreshes = 0;
    const stop = subscribeHistory(() => refreshes++);
    try {
      if (change === 'revision') deletionHistory(captureHistory(), '0'.repeat(64));
      else {
        const replace = (id, token) => activateSession(stampSession({ user: { id }, csrf_token: token }, new Response(null, { headers: { [HISTORY_HEADER]: '0'.repeat(64) } }), captureHistory()));
        replace(change === 'csrf' ? owner : other, 'replacement-csrf');
        if (change === 'owner-roundtrip') replace(owner, csrf);
      }
      const context = captureHistory(), count = refreshes;
      if (change === 'revision') assert.equal(value.accept(reply(value, 'accepted')), true);
      assert.equal(value.applyHistoryRevision('f'.repeat(64)), false);
      assert.equal(value.applyHistoryRevision(revision), false);
      assert.equal(captureHistory(), context); assert.equal(captureHistory().revision, '0'.repeat(64));
      assert.equal(refreshes, count);
    } finally { stop(); }
  }
});
test('strict replies distinguish logical acceptance, physical cleanup and unavailable/expired metadata', () => {
  const value = receipt();
  for (const state of ['awaiting_authority', 'accepted', 'purging', 'complete']) assert.equal(deletionReply(reply(value, state), value.context(), 200).job.state, state);
  assert.throws(() => deletionReply(reply(value, 'awaiting_authority'), value.context(), 202));
  const good = reply(value);
  for (const patch of [{ user_id: other }, { history_revision: '2' }, { private_data: [] }]) assert.throws(() => deletionReply({ ...good, ...patch }, value.context(), 202));
  for (const patch of [{ intent_id: other }, { scope: 'account_v1' }, { cleanup_complete: true }, { accepted: false }, { state: 'expired' }, { receipt_token: value.token() }, { receipt_expires_at: new Date(Date.now() - 1).toISOString() }, { receipt_expires_at: new Date(Date.now() + 601000).toISOString() }]) assert.throws(() => deletionReply({ ...good, job: { ...good.job, ...patch } }, value.context(), 202));
});
test('reducer requires explicit verification and confirmation, and uncertainty never becomes completion', () => {
  let state = initialDeletion(); assert.equal(deletionReducer(state, { type: 'submit' }), state);
  for (const type of ['verify', 'verifying', 'verified', 'submit', 'uncertain']) state = deletionReducer(state, { type });
  assert.equal(state.phase, 'uncertain'); assert.equal(state.job, null);
  assert.equal(deletionReducer(state, { type: 'submit' }), state);
  state = deletionReducer(state, { type: 'check' }); state = deletionReducer(state, { type: 'reply', job: { state: 'accepted', accepted: true, cleanup_complete: false } });
  assert.equal(state.phase, 'observing'); assert.equal(state.job.cleanup_complete, false);
  state = deletionReducer(state, { type: 'expired' }); assert.equal(state.job, null); assert.match(state.error, /does not confirm completion/);
  assert.doesNotMatch(JSON.stringify(state), /proof_token|receipt_token|synthetic-csrf/);
});
test('a later status outage cannot retract an already confirmed acceptance or infer completion', () => {
  const state = { phase: 'checking', job: { state: 'accepted', accepted: true, cleanup_complete: false }, error: '' };
  const failed = deletionReducer(state, { type: 'uncertain' });
  assert.equal(failed.job, state.job); assert.match(failed.error, /Deletion was accepted/); assert.equal(failed.job.cleanup_complete, false);
  const complete = { ...state, job: { state: 'complete', accepted: true, cleanup_complete: true } };
  assert.doesNotMatch(deletionReducer(complete, { type: 'expired' }).error, /Completion is unconfirmed/);
});
test('explicit creation uses the fixed POST body once, then purpose reconciliation uses only empty JSON and receipt header', async t => {
  const value = receipt(), calls = []; value.attempt();
  t.mock.method(globalThis, 'fetch', async (path, options) => { calls.push({ path, options }); return json(reply(value), calls.length === 1 ? 202 : 200); });
  const created = await startDataDeletion(value, proof); assert.equal(created.job.accepted, true);
  assert.throws(() => startDataDeletion(value, proof), { code: 'invalid_input' });
  // Local ordinary access may end, but this receipt can read minimal metadata.
  clearHistory(); const checked = await reconcileDataDeletion(value); assert.equal(checked.job.id, job);
  assert.equal(calls.length, 2); assert.equal(calls[0].path, '/api/v1/me/data-deletions');
  assert.equal(calls[1].path, '/api/v1/me/data-deletions/by-intent/' + value.intent);
  assert.equal(calls[0].options.headers[HISTORY_HEADER], revision);
  assert.equal(calls[1].options.headers['X-Aqua-Deletion-Receipt'], value.token());
  assert.deepEqual(JSON.parse(calls[1].options.body), {}); assert.equal(calls[1].options.headers['X-CSRF-Token'], csrf);
  for (const { path, options } of calls) { assert.ok(!path.includes(proof) && !path.includes(value.token())); assert.equal(options.method, 'POST'); assert.equal(options.credentials, 'same-origin'); assert.equal(options.redirect, 'error'); }
});
for (const status of [404, 503]) test('HTTP ' + status + ' remains unconfirmed and is never retried or treated as complete', async t => {
  const value = receipt(); value.attempt(); const fetch = t.mock.method(globalThis, 'fetch', async () => new Response('PRIVATE', { status }));
  await assert.rejects(startDataDeletion(value, proof), error => error.status === status && !error.message.includes('PRIVATE'));
  assert.equal(fetch.mock.calls.length, 1);
  await assert.rejects(reconcileDataDeletion(value), error => error.status === status);
  assert.equal(fetch.mock.calls.length, 2);
});
test('a lost creation response retains its original receipt for explicit check without replaying proof', async t => {
  const value = receipt(); value.attempt(); let calls = 0;
  t.mock.method(globalThis, 'fetch', async (_, options) => { calls++; if (calls === 1) throw Error('PRIVATE'); assert.deepEqual(JSON.parse(options.body), {}); return json(reply(value, 'awaiting_authority')); });
  await assert.rejects(startDataDeletion(value, proof), { code: 'unavailable' });
  const checked = await reconcileDataDeletion(value); assert.equal(checked.job.accepted, false); assert.equal(checked.job.cleanup_complete, false); assert.equal(calls, 2);
});
test('foreign intent, added authority, duplicate JSON, oversize response and invalid 202 cannot publish a job', async t => {
  const fetch = t.mock.method(globalThis, 'fetch', async () => json({}));
  for (const bad of ['foreign', 'added', 'duplicate', 'oversize', 'pending202']) {
    const value = receipt(); value.attempt(); const body = reply(value);
    fetch.mock.mockImplementation(async () => {
      if (bad === 'foreign') body.job.intent_id = other;
      if (bad === 'added') body.job.auth_epoch = 5;
      if (bad === 'pending202') return json(reply(value, 'awaiting_authority'), 202);
      if (bad === 'duplicate') return new Response('{"schemaVersion":1,"schemaVersion":1}', { headers: { 'Content-Type': 'application/json' } });
      if (bad === 'oversize') return new Response('x'.repeat(16385), { headers: { 'Content-Type': 'application/json' } });
      return json(body, 202);
    });
    await assert.rejects(startDataDeletion(value, proof), { code: 'invalid_response' });
  }
  assert.equal(fetch.mock.calls.length, 5);
});
test('closing an in-flight receipt suppresses a late accepted response', async t => {
  const value = receipt(); value.attempt(); let release, began; const fetching = new Promise(resolve => began = resolve);
  t.mock.method(globalThis, 'fetch', async () => { began(); return new Promise(resolve => release = resolve); });
  const pending = startDataDeletion(value, proof); await fetching;
  const accepted = reply(value); value.clear(); release(json(accepted, 202));
  await assert.rejects(pending, { name: 'AbortError' });
});
test('aborting a blocked receipt stream cancels the reader and wipes received metadata without retry', async t => {
  const value = receipt(), controller = new AbortController(); value.attempt();
  const chunk = new TextEncoder().encode('{"schemaVersion":1,'), headers = json({}).headers;
  let began, calls = 0, cancelled = 0; const reading = new Promise(resolve => began = resolve);
  const reader = { read: async () => { if (!calls++) return { done: false, value: chunk }; began(); return new Promise(() => {}); }, cancel: async () => { cancelled++; }, releaseLock() {} };
  const fetch = t.mock.method(globalThis, 'fetch', async () => ({ status: 202, redirected: false, headers, body: { getReader: () => reader } }));
  const pending = startDataDeletion(value, proof, { signal: controller.signal }); await reading; controller.abort();
  await assert.rejects(pending, { name: 'AbortError' }); assert.ok(cancelled >= 1); assert.ok(chunk.every(byte => byte === 0)); assert.equal(fetch.mock.calls.length, 1);
});
