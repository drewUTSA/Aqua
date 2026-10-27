// CI entry point: actual production assets + disposable real auth/history only.
import { writeFile, mkdir } from "node:fs/promises";
import path from "node:path";
import { openP08Browser, LIMITS } from "./p08-browser-environment.mjs";
import { runVisualChecks } from "./p08-browser-checks.mjs";
const EMAIL = "p05-browser-reader@example.test", PASSWORD = "Synthetic orbital meadow password 27";
let ctx, failure = null, stats = null, workload = null, failureState = null;
try {
  ctx = await openP08Browser(); ctx.secrets.add(PASSWORD);
  await ctx.navigate("/register"); await ctx.fill("#auth-email", EMAIL); await ctx.click("[data-testid=password-auth-submit]");
  await ctx.waitFor("location.pathname==='/registration-sent'", "registration_acknowledged");
  const mail = await ctx.bridge.send("mailbox", { purpose: "verify_email" });
  const proof = mail.proof; if (mail.found !== true || typeof proof !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(proof)) throw Error("synthetic_proof_invalid"); ctx.secrets.add(proof);
  await ctx.navigate(`/verify-email#token=${proof}`); await ctx.fill("#auth-password", PASSWORD); await ctx.fill("#auth-password-confirm", PASSWORD);
  await ctx.click("[data-testid=password-auth-submit]"); await ctx.waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", "verified_synthetic_account");
  await ctx.navigate("/signin"); await ctx.fill("#auth-email", EMAIL); await ctx.fill("#auth-password", PASSWORD); await ctx.click("[data-testid=password-auth-submit]");
  await ctx.waitFor("Boolean(document.querySelector('.opal-workspace'))", "password_session_ready");
  const me = await ctx.rawRequest("GET", "/api/auth/me");
  if (me.status !== 200 || JSON.parse(me.body).can_query !== false) throw Error("initial_grant_boundary_invalid");
  await ctx.bridge.send("workspace_grant"); await ctx.navigate("/");
  await ctx.waitFor("document.querySelector('.opal-composer textarea')?.disabled===false", "synthetic_grant_ready");
  workload = await runVisualChecks(ctx); stats = await ctx.bridge.send("workspace_stats");
  if (stats.actual_provider_calls !== 0 || stats.physical_active !== 0 || stats.maximum_physical_active !== 1 || stats.fake_executions !== workload.fake_jobs_requested || stats.fake_started !== workload.fake_jobs_requested || stats.fake_started > LIMITS.fakeJobs) throw Error("fixture_execution_boundary_invalid");
  if (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length) throw Error("browser_boundary_failure");
} catch { failure = ctx?.stage || "fixture_setup_failed";
  if (ctx?.bridge && !ctx.bridge.finished) { try { stats = await ctx.bridge.send("workspace_stats"); } catch { /* Fixed aggregate evidence only. */ } }
  if (ctx?.cdp && !ctx.cdp.failure) { try { failureState = await ctx.evaluate("(()=>{const p=document.querySelector('.visual-pane .js-plotly-plot');return {plot:Boolean(p),status:document.querySelector('.visual-pane .plotly-chart')?.dataset.chartStatus||null,autorange:p?.layout?.xaxis?.autorange??null,dragging:p?._dragging===true,transitioning:p?._transitioning===true,range:p?.layout?.xaxis?.range?.filter(Number.isFinite)||null}})()"); } catch { /* No raw exceptions or payload diagnostics. */ } }
}
finally { if (ctx) { try { await ctx.close(); } catch { failure ||= "cleanup_failed"; } } }
if (ctx && Object.entries(ctx.cleanup || {}).some(([key, value]) => key !== "backend" && value !== true)) failure ||= "cleanup_unconfirmed";
if (ctx && (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length)) failure ||= "browser_boundary_failure";
const report = { status: failure ? "failed" : "passed", failure, checked_utc: new Date().toISOString(), mode: "real_plotly_real_private_auth_history_fixed_fake_analysis",
  expected_shell: process.env.AQUA_P05_EXPECTED_SHELL || "opal", browser: ctx?.browserVersion || null, limits: LIMITS, workload, fixture: stats, failure_state: failureState,
  boundary: { backend_image: ctx?.backendImage || null, schema_version: 5, network: "none", private_synthetic_auth_history: true },
  elapsed_seconds: ctx ? Math.round((performance.now() - ctx.started) / 100) / 10 : null, browser_diagnostic: ctx?.cdp?.diagnostic || null,
  protocol_diagnostics: ctx?.protocolDiagnostics || [],
  observations: ctx ? { requests: ctx.requests, api_requests: ctx.api, external_attempts: ctx.external, runtime_errors: ctx.runtimeErrors, console_leaks: ctx.consoleLeaks, protocol_errors: ctx.errors, maximum_paused_requests: ctx.maximumPending } : null,
  engine_configuration: ctx?.engineConfiguration || null, active_control_contrast: ctx?.activeControlContrast ?? null, assets: ctx?.assets || [], checks: ctx?.results || [], screenshots: ctx?.screenshots || [], cleanup: ctx?.cleanup || null,
  limitations: ["All accounts, rows, grants and analysis are disposable synthetic fixtures; no live provider or business SQL.", "Clipboard and CSV Blob output are captured in memory through real UI callbacks; OS clipboard/download storage is not accessed."] };
const directory = process.env.AQUA_P08_ARTIFACT_DIR;
if (directory && path.isAbsolute(directory)) { await mkdir(directory, { recursive: true }); await writeFile(path.join(directory, "p08-browser-report.json"), JSON.stringify(report, null, 2) + "\n"); }
process.stdout.write(JSON.stringify({ status: report.status, failure, checks: report.checks.length, cleanup: report.cleanup?.backend_resources_removed === true }) + "\n");
process.exitCode = failure ? 1 : 0;
