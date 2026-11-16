// Fresh two-job fixture, separate from the full twelve-job P08 journey.
// Configure the same AQUA_P08_* variables as p08-browser.mjs; see
// WORKSPACE_RELIABILITY_BROWSER.md. No provider, production or test-cap change.
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { openP08Browser, LIMITS } from "./p08-browser-environment.mjs";
import { selectedResultTableReset } from "./workspace-reliability-browser.mjs";
import { assertLoginDelivery } from "./p05-shell-browser-checks.mjs";
import { assertCspCoverage } from "./csp-browser-probes.mjs";

const EMAIL = "p05-browser-reader@example.test", PASSWORD = "Synthetic orbital meadow password 27";
let ctx, failure = null, stats = null, jobs = 0;
try {
  ctx = await openP08Browser({ cspEnforcedFixture: true }); ctx.secrets.add(PASSWORD);
  await ctx.navigate("/register"); await ctx.fill("#auth-email", EMAIL); await ctx.click("[data-testid=password-auth-submit]");
  await ctx.waitFor("location.pathname==='/registration-sent'", "registration_acknowledged");
  const mail = await ctx.bridge.send("mailbox", { purpose: "verify_email" });
  if (mail.found !== true || typeof mail.proof !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(mail.proof)) throw Error("synthetic_proof_invalid");
  ctx.secrets.add(mail.proof);
  await ctx.navigate(`/verify-email#token=${mail.proof}`); await ctx.fill("#auth-password", PASSWORD); await ctx.fill("#auth-password-confirm", PASSWORD);
  await ctx.click("[data-testid=password-auth-submit]"); await ctx.waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", "verified_synthetic_account");
  await ctx.navigate("/signin"); await assertLoginDelivery(ctx.check); await ctx.fill("#auth-email", EMAIL); await ctx.fill("#auth-password", PASSWORD); await ctx.click("[data-testid=password-auth-submit]");
  await ctx.waitFor("Boolean(document.querySelector('.opal-workspace'))", "password_session_ready");
  const me = await ctx.rawRequest("GET", "/api/auth/me");
  if (me.status !== 200 || JSON.parse(me.body).can_query !== false) throw Error("initial_grant_boundary_invalid");
  await ctx.bridge.send("workspace_grant"); await ctx.navigate("/");
  await ctx.waitFor("document.querySelector('.opal-composer textarea')?.disabled===false", "synthetic_grant_ready");
  const submit = async (question) => {
    if (question !== "P08 chart oversized" || jobs >= 2) throw Error("fixed_table_case_budget");
    const before = await ctx.evaluate("document.querySelectorAll('.conversation .visual-result-open').length");
    await ctx.fill(".opal-composer textarea", question); await ctx.click('[aria-label="Send message"]'); jobs++;
    await ctx.waitFor(`document.querySelectorAll('.conversation .visual-result-open').length>${before}&&Boolean(document.querySelector('.analysis-status[data-analysis-state=complete]'))&&!document.querySelector('[aria-label="Cancel analysis"]')`, "fixed_table_analysis_terminal");
  };
  await selectedResultTableReset(ctx, submit);
  stats = await ctx.bridge.send("workspace_stats");
  if (jobs !== 2 || stats.actual_provider_calls !== 0 || stats.fake_executions !== 2 || stats.fake_started !== 2 || stats.physical_active !== 0 || stats.maximum_physical_active !== 1 || stats.fake_started > LIMITS.fakeJobs) throw Error("fixture_execution_boundary_invalid");
  assertCspCoverage(ctx.csp);
  if (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length) throw Error("browser_boundary_failure");
} catch {
  failure = ctx?.stage || "fixture_setup_failed";
  if (ctx?.bridge && !ctx.bridge.finished) { try { stats = await ctx.bridge.send("workspace_stats"); } catch { /* Fixed metadata only. */ } }
} finally { if (ctx) { try { await ctx.close(); } catch { failure ||= "cleanup_failed"; } } }
if (ctx && Object.entries(ctx.cleanup || {}).some(([key, value]) => key !== "backend" && value !== true)) failure ||= "cleanup_unconfirmed";
if (ctx && (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length)) failure ||= "browser_boundary_failure";
const report = { status: failure ? "failed" : "passed", failure, checked_utc: new Date().toISOString(),
  mode: "fresh_two_fixed_table_results_real_private_fixture", expected_shell: process.env.AQUA_P05_EXPECTED_SHELL || "opal",
  limits: LIMITS, fake_jobs_requested: jobs, fixture: stats, browser: ctx?.browserVersion || null,
  boundary: { backend_image: ctx?.backendImage || null, schema_version: ctx?.schemaVersion ?? null, network: "none", live_provider_or_production: false },
  content_security_policy: ctx?.csp || null, assets: ctx?.assets || [], checks: ctx?.results || [], screenshots: ctx?.screenshots || [], cleanup: ctx?.cleanup || null,
  observations: ctx ? { requests: ctx.requests, api_requests: ctx.api, external_attempts: ctx.external, runtime_errors: ctx.runtimeErrors, console_leaks: ctx.consoleLeaks, protocol_errors: ctx.errors } : null,
  elapsed_seconds: ctx ? Math.round((performance.now() - ctx.started) / 100) / 10 : null,
  limitations: ["Two fixed synthetic analyses in a separate disposable fixture; no real provider or business SQL.", "CSP enforcement is fixture-only, not a production TLS or Google provider acceptance claim."] };
const directory = process.env.AQUA_P08_ARTIFACT_DIR;
if (directory && path.isAbsolute(directory)) { await mkdir(directory, { recursive: true }); await writeFile(path.join(directory, "p08-table-reset-report.json"), JSON.stringify(report, null, 2) + "\n"); }
process.stdout.write(JSON.stringify({ status: report.status, failure, checks: report.checks.length, fake_jobs_requested: jobs, cleanup: report.cleanup?.backend_resources_removed === true }) + "\n");
process.exitCode = failure ? 1 : 0;
