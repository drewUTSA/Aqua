import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { openP08Browser, LIMITS } from './p08-browser-environment.mjs';
import { GOOGLE_FIXTURE_SCRIPT } from './p10c-identity-browser-checks.mjs';
import { DELETION_SCRIPT, runRealDeletionChecks } from './p11b-real-deletion-checks.mjs';
for (const name of ['DIST', 'ARTIFACT_DIR', 'BRIDGE_EXECUTABLE', 'BRIDGE_ARGS_JSON']) {
  if (process.env['AQUA_P11B_' + name]) process.env['AQUA_P08_' + name] = process.env['AQUA_P11B_' + name];
}
let ctx, workload = null, failure = null, setup = null, diagnostic = null;
try {
  ctx = await openP08Browser({ secureAccountFixture: true, personalDeletionFixture: true });
  const ready = await ctx.bridge.ready;
  if (!ctx.personalDeletionFixture || !ready.identity_fixture?.actual_independent_authority) throw Error('actual_deletion_fixture_required');
  await ctx.cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: GOOGLE_FIXTURE_SCRIPT });
  await ctx.cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: DELETION_SCRIPT });
  workload = await runRealDeletionChecks(ctx);
} catch (error) {
  setup = error.setupDiagnostic || null;
  failure = ctx?.stage || (/^[a-z0-9_]{1,96}$/.test(error?.message || '') ? error.message : 'fixture_setup_failed');
  if (ctx) {
    try {
      diagnostic = await ctx.evaluate(`(()=>{const input=document.querySelector('.opal-composer textarea'),send=document.querySelector('[aria-label="Send message"]');return {path:location.pathname,phase:document.querySelector('[data-deletion-phase]')?.dataset.deletionPhase||null,workspace:!!document.querySelector('.opal-workspace:not([hidden])'),composer:!!input,composer_disabled:input?.disabled??null,draft_length:input?.value.length??null,send:!!send,send_disabled:send?.disabled??null,open_dialogs:document.querySelectorAll('dialog[open]').length,analysis_complete:document.querySelectorAll('.analysis-status[data-analysis-state=complete]').length,deletion_audit:window.__deletionAudit||[]}})()`);
      await ctx.screenshot('p11b-bounded-failure');
    } catch { /* Preserve the original fixed failure if the browser already stopped. */ }
  }
} finally {
  if (ctx) { try { await ctx.close(); } catch { failure ||= 'cleanup_failed'; } }
}
if (ctx && Object.entries(ctx.cleanup || {}).some(([key, value]) => key !== 'backend' && value !== true)) failure ||= 'cleanup_unconfirmed';
if (ctx && (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length)) failure ||= 'browser_boundary_failure';
const report = { status: failure ? 'failed' : 'passed', failure, checked_utc: new Date().toISOString(), mode: 'actual_schema9_two_database_signed_retirement_reserved_https_cdp',
  expected_shell: process.env.AQUA_P05_EXPECTED_SHELL || 'opal',
  limits: LIMITS, workload, setup_diagnostic: setup, failure_diagnostic: diagnostic, checks: ctx?.results || [], screenshots: ctx?.screenshots || [], assets: ctx?.assets || [], cleanup: ctx?.cleanup || null,
  observations: ctx ? { requests: ctx.requests, api_requests: ctx.api, maximum_paused: ctx.maximumPending, external_attempts: ctx.external, runtime_errors: ctx.runtimeErrors, console_leaks: ctx.consoleLeaks, protocol_errors: ctx.errors } : null,
  boundary: { production_changed: false, provider_calls: 0, schema_version: 9, network: 'none', backend_image: ctx?.backendImage || null, synthetic_authority: false },
  limitations: ['Reserved HTTPS assets and real API responses are fulfilled through CDP; DNS/TCP/TLS are not exercised.', 'Google assertions and the two analytical answers are explicitly synthetic; no provider or analytical database is called.', 'The isolated tmpfs append-only ioctl and production physical-mail bind are explicit seams; real SQL, signatures, file writes/fsync, app guards and bounded cleanup execute.', 'Background deletion scheduling uses bounded explicit calls to the unchanged Worker.once; this journey does not prove daemon restart recovery.', 'The fixed response bridge uses polling rather than progressive SSE.'] };
const directory = process.env.AQUA_P11B_ARTIFACT_DIR || process.env.AQUA_P08_ARTIFACT_DIR;
if (directory) { await mkdir(directory, { recursive: true }); await writeFile(path.join(directory, 'p11b-real-deletion-report.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ status: report.status, failure, checks: report.checks.length, cleanup: report.cleanup }));
process.exitCode = failure ? 1 : 0;
