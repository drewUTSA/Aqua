import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { openP08Browser, LIMITS } from "./p08-browser-environment.mjs";
import { runSecurityChecks, SECURITY_SCENARIOS } from "./p10b-security-browser-checks.mjs";

for (const name of ["DIST", "ARTIFACT_DIR", "BRIDGE_EXECUTABLE", "BRIDGE_ARGS_JSON"]) {
  if (process.env["AQUA_P10B_" + name]) process.env["AQUA_P08_" + name] = process.env["AQUA_P10B_" + name];
}
const scenario = process.env.AQUA_P10B_SCENARIO || "revoke-other";
const EMAIL = "p05-browser-reader@example.test", PASSWORD = "Synthetic orbital meadow password 27", NEXT_PASSWORD = "Synthetic cedar hillside password 42";
let ctx, failure = null, setup = null, workload = null, stats = null;
try {
  if (!SECURITY_SCENARIOS.has(scenario)) throw Error("security_scenario_invalid");
  ctx = await openP08Browser({ secureAccountFixture: true }); ctx.secrets.add(PASSWORD); ctx.secrets.add(NEXT_PASSWORD);
  await ctx.navigate("/register"); await ctx.fill("#auth-email", EMAIL); await ctx.click("[data-testid=password-auth-submit]");
  await ctx.waitFor("location.pathname==='/registration-sent'", "registration_acknowledged");
  const mail = await ctx.bridge.send("mailbox", { purpose: "verify_email" });
  if (mail.found !== true || typeof mail.proof !== "string" || !/^[A-Za-z0-9_-]{43}$/.test(mail.proof)) throw Error("synthetic_proof_invalid");
  ctx.secrets.add(mail.proof);
  await ctx.navigate("/verify-email#token=" + mail.proof); await ctx.fill("#auth-password", PASSWORD); await ctx.fill("#auth-password-confirm", PASSWORD);
  await ctx.click("[data-testid=password-auth-submit]"); await ctx.waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", "verified_synthetic_account");
  await ctx.navigate("/signin"); await ctx.fill("#auth-email", EMAIL); await ctx.fill("#auth-password", PASSWORD); await ctx.click("[data-testid=password-auth-submit]");
  await ctx.waitFor("Boolean(document.querySelector('.opal-workspace'))", "password_session_ready");
  workload = await runSecurityChecks(ctx, { scenario, email: EMAIL, password: PASSWORD, newPassword: NEXT_PASSWORD });
  stats = await ctx.bridge.send("workspace_stats");
  if (stats.actual_provider_calls !== 0 || stats.fake_started !== 0 || stats.physical_active !== 0) throw Error("security_started_analysis");
} catch (error) {
  setup = error.setupDiagnostic || null;
  failure = ctx?.stage || (/^[a-z0-9_]{1,96}$/.test(error?.message || "") ? error.message : "fixture_setup_failed");
} finally { if (ctx) { try { await ctx.close(); } catch { failure ||= "cleanup_failed"; } } }
if (ctx && Object.entries(ctx.cleanup || {}).some(([key, value]) => key !== "backend" && value !== true)) failure ||= "cleanup_unconfirmed";
if (ctx && (ctx.external || ctx.runtimeErrors || ctx.consoleLeaks || ctx.errors.length)) failure ||= "browser_boundary_failure";
const report = { status: failure ? "failed" : "passed", failure, checked_utc: new Date().toISOString(), mode: "real_p10b_private_account_api_cdp_reserved_https_origin",
  scenario: SECURITY_SCENARIOS.has(scenario) ? scenario : "invalid", expected_shell: process.env.AQUA_P05_EXPECTED_SHELL || "opal",
  elapsed_seconds: ctx ? Math.round((performance.now() - ctx.started) / 100) / 10 : null,
  limits: LIMITS, workload, fixture: stats, secure_origin: ctx?.secureAccountFixture || null,
  boundary: { backend_image: ctx?.backendImage || null, schema_version: 6, network: "none", live_provider_or_production: false, dns_socket_tls_transport_tested: false },
  browser_diagnostic: ctx?.cdp?.diagnostic || null, protocol_diagnostics: ctx?.protocolDiagnostics || [], setup_diagnostic: setup,
  checks: ctx?.results || [], screenshots: ctx?.screenshots || [], assets: ctx?.assets || [], cleanup: ctx?.cleanup || null,
  observations: ctx ? { requests: ctx.requests, api_requests: ctx.api, external_attempts: ctx.external, runtime_errors: ctx.runtimeErrors,
    console_leaks: ctx.consoleLeaks, protocol_errors: ctx.errors, maximum_paused_requests: ctx.maximumPending } : null,
  limitations: ["The reserved HTTPS origin is fulfilled from frozen bytes by CDP; no DNS, TCP or TLS transport is exercised.",
    "Real Chrome secure-context and host-only Secure HttpOnly cookie behavior is exercised without certificate installation or Origin rewriting.",
    "Each scenario requires a fresh isolated fixture; server quotas, clocks, proof expiry and challenge consumption are never relaxed.",
    "Only the fake encrypted mail worker handles the required security notice. No real provider, analytical data or live email is used."] };
const directory = process.env.AQUA_P10B_ARTIFACT_DIR || process.env.AQUA_P08_ARTIFACT_DIR;
if (directory && path.isAbsolute(directory)) { await mkdir(directory, { recursive: true }); await writeFile(path.join(directory, "p10b-security-browser-report.json"), JSON.stringify(report, null, 2) + "\n"); }
console.log(JSON.stringify({ status: report.status, failure, scenario: report.scenario, checks: report.checks.length, cleanup: report.cleanup?.backend_resources_removed === true, setup_diagnostic: setup }));
process.exitCode = failure ? 1 : 0;
