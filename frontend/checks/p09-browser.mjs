// Separate P09 fixture preserves P08's unchanged bounds and grant-free Settings.
import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { openP08Browser, LIMITS } from './p08-browser-environment.mjs';
import { runPreferenceChecks } from './p09-browser-checks.mjs';

for (const name of ['DIST', 'ARTIFACT_DIR', 'BRIDGE_EXECUTABLE', 'BRIDGE_ARGS_JSON']) {
  if (process.env['AQUA_P09_' + name]) process.env['AQUA_P08_' + name] = process.env['AQUA_P09_' + name];
}
const EMAIL = 'p05-browser-reader@example.test', PASSWORD = 'Synthetic orbital meadow password 27';
let ctx, failure = null, workload = null, stats = null, setup = null;
try {
  ctx = await openP08Browser(); ctx.secrets.add(PASSWORD);
  await ctx.navigate('/register'); await ctx.fill('#auth-email', EMAIL); await ctx.click('[data-testid=password-auth-submit]');
  await ctx.waitFor("location.pathname==='/registration-sent'", 'registration_acknowledged');
  const mail = await ctx.bridge.send('mailbox', { purpose: 'verify_email' });
  if (mail.found !== true || typeof mail.proof !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(mail.proof)) throw Error('synthetic_proof_invalid');
  ctx.secrets.add(mail.proof);
  await ctx.navigate('/verify-email#token=' + mail.proof); await ctx.fill('#auth-password', PASSWORD); await ctx.fill('#auth-password-confirm', PASSWORD);
  await ctx.click('[data-testid=password-auth-submit]'); await ctx.waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", 'verified_synthetic_account');
  await ctx.navigate('/signin'); await ctx.fill('#auth-email', EMAIL); await ctx.fill('#auth-password', PASSWORD); await ctx.click('[data-testid=password-auth-submit]');
  await ctx.waitFor("Boolean(document.querySelector('.opal-workspace'))", 'password_session_ready');
  const me = await ctx.rawRequest('GET', '/api/auth/me');
  if (me.status !== 200 || JSON.parse(me.body).can_query !== false) throw Error('unexpected_dataset_grant');
  workload = await runPreferenceChecks(ctx);
  stats = await ctx.bridge.send('workspace_stats');
  if (stats.actual_provider_calls !== 0 || stats.fake_started !== 0 || stats.physical_active !== 0) throw Error('settings_started_analysis');
} catch (error) { setup = error.setupDiagnostic || null; failure = ctx?.stage || (/^[a-z0-9_]{1,96}$/.test(error?.message || '') ? error.message : 'fixture_setup_failed'); }
finally { if (ctx) { try { await ctx.close(); } catch { failure ||= 'cleanup_failed'; } } }
if (ctx && Object.entries(ctx.cleanup || {}).some(([key, value]) => key !== 'backend' && value !== true)) failure ||= 'cleanup_unconfirmed';
if (ctx && (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length)) failure ||= 'browser_boundary_failure';
const report = { status: failure ? 'failed' : 'passed', failure, checked_utc: new Date().toISOString(), mode: 'real_settings_current_owner_private_db_no_dataset_grant',
  elapsed_seconds: ctx ? Math.round((performance.now() - ctx.started) / 100) / 10 : null,
  expected_shell: process.env.AQUA_P05_EXPECTED_SHELL || 'opal', limits: LIMITS, workload, fixture: stats,
  browser_diagnostic: ctx?.cdp?.diagnostic || null, protocol_diagnostics: ctx?.protocolDiagnostics || [],
  setup_diagnostic: setup,
  boundary: { backend_image: ctx?.backendImage || null, schema_version: 8, network: 'none', live_provider_or_production: false },
  appearance_audit: ctx?.appearanceAudit || null, mobile_category_audit: ctx?.mobileCategoryAudit || null, accessibility_tree_audit: ctx?.accessibilityTreeAudit || null, mobile_text_audit: ctx?.mobileTextAudit || null,
  mobile_overflow_audit: ctx?.mobileOverflowAudit || [],
  checks: ctx?.results || [], screenshots: ctx?.screenshots || [], cleanup: ctx?.cleanup || null,
  observations: ctx ? { requests: ctx.requests, api_requests: ctx.api, external_attempts: ctx.external, runtime_errors: ctx.runtimeErrors, console_leaks: ctx.consoleLeaks, protocol_errors: ctx.errors, maximum_paused_requests: ctx.maximumPending } : null,
  assets: ctx?.assets || [], limitations: ['P08 visual interactions run in their separate unchanged fixture.', '320px/doubled-root-text check does not claim assistive-technology or full browser-zoom coverage.'] };
const directory = process.env.AQUA_P09_ARTIFACT_DIR || process.env.AQUA_P08_ARTIFACT_DIR;
if (directory && path.isAbsolute(directory)) { await mkdir(directory, { recursive: true }); await writeFile(path.join(directory, 'p09-browser-report.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ status: report.status, failure, checks: report.checks.length, browser_diagnostic: report.browser_diagnostic, setup_diagnostic: setup, cleanup: report.cleanup?.backend_resources_removed === true }));
process.exitCode = failure ? 1 : 0;
