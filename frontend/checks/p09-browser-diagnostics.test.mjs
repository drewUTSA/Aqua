import test from 'node:test';
import assert from 'node:assert/strict';
import { setupDiagnostic } from './p08-browser-environment.mjs';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { BrowserPipe } from './p05-browser-pipe.mjs';

test('a failed startup stays red even when the actual owned child exits and closes its pipes', async t => {
  // This confined Node fixture stays alive without answering the CDP request.
  const child = spawn(process.execPath, ['-e', 'process.stdin.resume(); setInterval(() => {}, 1000)'],
    { windowsHide: true, stdio: ['ignore', 'ignore', 'ignore', 'pipe', 'pipe'] });
  const pipe = new BrowserPipe(child);
  t.after(() => { if (!pipe.stopped) child.kill(); });
  await once(child, 'spawn');
  t.mock.timers.enable({ apis: ['setTimeout'] });
  const rejected = assert.rejects(pipe.ready(), { message: 'browser_protocol_deadline' });
  t.mock.timers.tick(30000);
  t.mock.timers.reset();
  await rejected;
  await pipe.stop();
  const strict = pipe.stopped === true && !pipe.cleanupFailure;
  const report = setupDiagnostic(new Error(pipe.failure), { cdp: pipe, cleanup: { browser_stopped: strict } });
  assert.equal(strict, false);
  assert.equal(report.category, 'browser_protocol_deadline');
  assert.equal(report.browser.timeout_ms, 30000);
  assert.equal(report.browser.signal_sent, true);
  assert.equal(report.browser.child_exit_observed, true);
  assert.equal(report.browser.stdio_close_observed, true);
  assert.equal(report.cleanup.browser_stopped, false);
});

test('a sent signal alone does not prove child exit or closed stdio', () => {
  const report = setupDiagnostic(new Error('browser_protocol_deadline'), { cdp: {
    child: { killed: true, exitCode: null, signalCode: null }, drained: false, closeKind: 'PRIVATE_TEXT',
    diagnostic: { timeout_ms: 'PRIVATE_TEXT', elapsed_ms: Infinity },
  }, cleanup: { browser_stopped: false } });
  assert.equal(report.browser.child_exit_observed, false);
  assert.equal(report.browser.stdio_close_observed, false);
  assert.equal(report.browser.signal_sent, true);
  assert.equal(report.browser.close_kind, null);
  assert.equal(report.browser.timeout_ms, null);
  assert.equal(report.browser.elapsed_ms, null);
  assert.equal(JSON.stringify(report).includes('PRIVATE_TEXT'), false);
});

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
