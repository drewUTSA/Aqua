import { mkdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { openP08Browser, LIMITS } from './p08-browser-environment.mjs';
import { GOOGLE_FIXTURE_SCRIPT, googleCallback } from './p10c-identity-browser-checks.mjs';
import { EXPORT_FIXTURE_SCRIPT, runExportChecks } from './p11a-export-browser-checks.mjs';
import { EXPORT_SCENARIOS, exportScenario, exportFixtureBoundary } from './p11a-export-browser-contract.mjs';
for (const name of ['DIST', 'ARTIFACT_DIR', 'BRIDGE_EXECUTABLE', 'BRIDGE_ARGS_JSON']) {
  if (process.env['AQUA_P11A_' + name]) process.env['AQUA_P08_' + name] = process.env['AQUA_P11A_' + name];
}
const scenario = process.env.AQUA_P11A_SCENARIO || 'password-export';
const PASSWORD = 'Synthetic orbital meadow password 27';
let ctx, failure = null, setup = null, workload = null, stats = null;
const observed = [];
try {
  exportScenario(scenario);
  ctx = await openP08Browser({ secureAccountFixture: true });
  if (ctx.personalExportFixture !== true || ctx.accountIdentityFixture !== true) throw Error('personal_export_fixture_required');
  ctx.secrets.add(PASSWORD);ctx.secrets.add('Synthetic incorrect export password');
  const previous = ctx.cdp.onEvent;
  ctx.cdp.onEvent = event => {
    if (event.sessionId === ctx.sessionId && event.method === 'Fetch.requestPaused') {
      const request = event.params.request, url = new URL(request.url);
      if (url.origin === ctx.origin && /^\/api\/v1\/me\/(?:data-exports|reauth)/.test(url.pathname)) {
        if (observed.length >= 128) { ctx.cdp.fail('export_observed_request_bound'); return; }
        const route = url.pathname.replace(/\/by-intent\/[a-f0-9-]+$/, '/by-intent/:intent_id')
          .replace(/\/data-exports\/[a-f0-9-]+(?=\/|$)/, '/data-exports/:job_id');
        observed.push({ route, method: request.method });
      }
    }
    previous(event);
  };
  await ctx.cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: GOOGLE_FIXTURE_SCRIPT });
  await ctx.cdp.send('Page.addScriptToEvaluateOnNewDocument', { source: EXPORT_FIXTURE_SCRIPT });
  if (scenario === 'google-export') {
    await ctx.navigate('/signin');await googleCallback(ctx, 'owner');
    await ctx.waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", 'export_google_login_ready');
  } else {
    await ctx.navigate('/register');await ctx.fill('#auth-email', 'p05-browser-reader@example.test');await ctx.click('[data-testid=password-auth-submit]');
    await ctx.waitFor("location.pathname==='/registration-sent'", 'export_registration_acknowledged');
    const mail = await ctx.bridge.send('mailbox', { purpose: 'verify_email' });
    if (mail.found !== true || typeof mail.proof !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(mail.proof)) throw Error('export_registration_proof_invalid');
    ctx.secrets.add(mail.proof);await ctx.navigate('/verify-email#token=' + mail.proof);
    await ctx.fill('#auth-password', PASSWORD);await ctx.fill('#auth-password-confirm', PASSWORD);await ctx.click('[data-testid=password-auth-submit]');
    await ctx.waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", 'export_password_account_ready');
    await ctx.navigate('/signin');await ctx.fill('#auth-email', 'p05-browser-reader@example.test');await ctx.fill('#auth-password', PASSWORD);await ctx.click('[data-testid=password-auth-submit]');
    await ctx.waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", 'export_password_login_ready');
  }
  workload = await runExportChecks(ctx, { scenario, password: PASSWORD });
  const proofPosts = observed.filter(item => item.method === 'POST' && item.route.startsWith('/api/v1/me/reauth')).length;
  const createPosts = observed.filter(item => item.method === 'POST' && item.route === '/api/v1/me/data-exports').length;
  const downloads = observed.filter(item => item.method === 'GET' && item.route === '/api/v1/me/data-exports/:job_id/download').length;
  if (proofPosts !== workload.proof_posts || createPosts !== workload.create_posts || downloads !== workload.download_gets) throw Error('export_exact_request_counts_invalid');
  workload = { ...workload, observed_action_requests: observed, actual_provider_calls: 0, real_google_sdk_calls: 0,
    fake_jobs_requested: 0, fixture_dataset_grant: false, server_quota_clock_or_limit_changes: 0, OS_downloads_requested: 0,
    export_body_transport_cap_bytes: LIMITS.bodyBytes, large_multichunk_expiry_capacity_scope: 'canonical_backend_tests_and_offline_client_tests' };
  stats = await ctx.bridge.send('workspace_stats');exportFixtureBoundary(stats);
} catch (error) {
  setup = error.setupDiagnostic || null;
  failure = ctx?.stage || (/^[a-z0-9_]{1,96}$/.test(error?.message || '') ? error.message : 'fixture_setup_failed');
} finally {
  if (ctx) { try { await ctx.close(); } catch { failure ||= 'cleanup_failed'; } }
}
if (ctx && Object.entries(ctx.cleanup || {}).some(([key, value]) => key !== 'backend' && value !== true)) failure ||= 'cleanup_unconfirmed';
if (ctx && (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length)) failure ||= 'browser_boundary_failure';
const report = { status: failure ? 'failed' : 'passed', failure, checked_utc: new Date().toISOString(),
  mode: 'real_p11a_private_export_api_cdp_reserved_https_origin', scenario: EXPORT_SCENARIOS.includes(scenario)?scenario:'invalid', expected_shell: process.env.AQUA_P05_EXPECTED_SHELL || 'opal',
  elapsed_seconds: ctx ? Math.round((performance.now() - ctx.started) / 100) / 10 : null, limits: LIMITS,
  workload, fixture: stats, secure_origin: ctx?.secureAccountFixture || null,
  boundary: { backend_image: ctx?.backendImage || null, schema_version: 8, network: 'none', live_provider_or_production: false, dns_socket_tls_transport_tested: false },
  browser_diagnostic: ctx?.cdp?.diagnostic || null, protocol_diagnostics: ctx?.protocolDiagnostics || [], setup_diagnostic: setup,
  checks: ctx?.results || [], screenshots: ctx?.screenshots || [], assets: ctx?.assets || [], cleanup: ctx?.cleanup || null,
  observations: ctx ? { requests: ctx.requests, api_requests: ctx.api, maximum_paused_requests: ctx.maximumPending,
    external_attempts: ctx.external, runtime_errors: ctx.runtimeErrors, console_leaks: ctx.consoleLeaks, protocol_errors: ctx.errors } : null,
  limitations: ['The reserved HTTPS origin is fulfilled from frozen bytes through CDP; no DNS, TCP or TLS transport is exercised.',
    'Real API, proof, owner, worker and database checks handle a small synthetic export within the unchanged16KiB browser bridge cap.',
    'Partial/digest faults modify only the already-returned real response in the two explicitly labeled local transport journeys.',
    'Native browser SHA-256 verifies real bytes. Anchor clicks are intercepted; no OS download or successful device save is claimed.',
    'Canonical backend tests separately cover physical64KiB chunks,32MiB output, expiry, concurrency, restore and disconnect behavior.',
    'Synthetic one-use Google assertions replace provider signature verification; no real Google, mail, model or analytical grant is used.'] };
const directory = process.env.AQUA_P11A_ARTIFACT_DIR || process.env.AQUA_P08_ARTIFACT_DIR;
if (directory && path.isAbsolute(directory)) { await mkdir(directory, { recursive: true }); await writeFile(path.join(directory, 'p11a-export-browser-report.json'), JSON.stringify(report, null, 2) + '\n'); }
console.log(JSON.stringify({ status: report.status, failure, scenario: report.scenario, checks: report.checks.length, cleanup: report.cleanup?.backend_resources_removed === true, setup_diagnostic: setup }));
process.exitCode = failure ? 1 : 0;
