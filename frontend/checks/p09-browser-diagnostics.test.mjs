import test from 'node:test';
import assert from 'node:assert/strict';
import { setupDiagnostic } from './p08-browser-environment.mjs';

test('setup diagnostics retain fixed categories and bounded cleanup metadata only', () => {
  const result = setupDiagnostic(new Error('fixture_worker_not_ready'), { stage: 'configuration', bridge: { diagnostic: { kind: 'error', category: 'RuntimeError', stage: 'migration', module: 'storage.runtime', payload: 'PRIVATE_PAYLOAD' } }, cleanup: { browser_stopped: true, profile_removed: true, loopback_closed: true, backend_resources_removed: true, backend: { status: 'passed', cleanup: 'removed_and_absence_confirmed', remaining_ids: [], account: 'PRIVATE_ACCOUNT' } } });
  assert.equal(result.category, 'fixture_worker_not_ready'); assert.equal(result.bridge.stage, 'migration');
  assert.equal(result.cleanup.remaining_resources, 0); assert.equal(JSON.stringify(result).includes('PRIVATE_'), false);
});
test('setup diagnostics redact paths, payload-bearing messages and unsupported fields', () => {
  const result = setupDiagnostic(new Error('C:\\private\\account token-secret'), { stage: 'private account', cdp: { diagnostic: { reason: 'browser_protocol_method_rejected', method: 'Runtime.evaluate', pending_count: 1, expression: 'PRIVATE_EXPRESSION' } }, bridge: { diagnostic: { kind: 'error', category: 'private payload', stage: 'private/path' } } });
  assert.equal(result.category, 'Error'); assert.equal(result.stage, 'configuration'); assert.equal(result.bridge.category, null);
  assert.equal(result.browser.method, 'Runtime.evaluate'); assert.equal(JSON.stringify(result).includes('private'), false); assert.equal(JSON.stringify(result).includes('PRIVATE_'), false);
});
