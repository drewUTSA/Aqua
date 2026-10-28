// Actual FastAPI + disposable PostgreSQL browser gate. No production service is
// contacted. The reviewed JSONL bridge owns fixture DB/outbox setup and cleanup.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { FixtureBridge } from "./p05-browser-bridge.mjs";
import { BrowserPipe } from "./p05-browser-pipe.mjs";
import { accountAction } from "./homepage-browser-actions.mjs";
import { actualPersonalWorkspace, foreignPersonalWorkspace } from "./p06-real-browser-checks.mjs";
import { actualAnalysisWorkspace } from "./p06-analysis-browser-checks.mjs";
import { createServer } from "node:http";
import { readFile, readdir, lstat, realpath, mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { EXPECTED_SHELL, assertShell, assertLoginDelivery, capturePerformance } from "./p05-shell-browser-checks.mjs";

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function configuredPath(name, fallback) {
  const value = process.env[name] || fallback;
  if (value.length > 4096 || value.includes("\0") || !path.isAbsolute(value)) throw new Error("artifact_path_invalid");
  return path.resolve(value);
}
const artifacts = configuredPath("AQUA_P05_ARTIFACT_DIR", path.resolve(frontend, "../../real-browser-evidence"));
const distRoot = configuredPath("AQUA_P05_DIST", path.join(frontend, "dist"));
let loadedAssets = [];
async function ensureArtifacts() {
  await mkdir(artifacts, { recursive: true });
  if ((await lstat(artifacts)).isSymbolicLink()) throw new Error("artifact_directory_symlink_rejected");
}
// P07 adds bounded status polling and reloads. This includes static requests;
// the independent backend fixture still caps opt-in operations at 400.
const MAX_MS = 240000, MAX_BODY = 16384, MAX_REQUESTS = 512;
const analysisFixture = process.env.AQUA_P06_ANALYSIS_FIXTURE === "true";
const EMAIL = "p05-browser-reader@example.test";
const PASSWORD = "Synthetic orbital meadow password 27";
const NEXT_PASSWORD = "Synthetic restored mountain password 48";
const started = performance.now(), results = [], screenshots = [], performanceSamples = [];
const proofValues = [], browserErrors = [], protocolErrors = [];
const sensitiveValues = new Set([PASSWORD, NEXT_PASSWORD]);
const apiOutcomes = [];
const abortedNetworkRequests = new Set();
let browser, bridge, cdp, profile, server, origin, sessionId, deadline, failure = null, failureDiagnostic = null, firstAccountWorkspace = null, currentStep='setup', failureStep=null;
let requests = 0, apiRequests = 0, external = 0, consoleLeaks = 0, bridgeCleanup = null;
let navigating = false, canceled = 0, staticCount = 0, fixtureClockSteps = 0, analysisClockSteps = 0;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const quote = JSON.stringify;

async function evaluate(expression) {
  const value = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (value.exceptionDetails) throw new Error("page_evaluation_failed");
  return value.result.value;
}
async function waitFor(expression, label, ms = 15000) {
  currentStep=label;
  const until = performance.now() + ms;
  while (performance.now() < until) { if (await evaluate(expression)) return; await delay(40); }
  throw new Error(`condition_failed:${label}`);
}
async function check(label, expression) { currentStep=label;assert.equal(await evaluate(expression), true, label); results.push({ check: label, passed: true }); }
async function navigate(route) {
  navigating = true;
  try {
    await cdp.send("Page.navigate", { url: "about:blank" }); await waitFor("location.href==='about:blank'", "document_reset");
    await cdp.send("Page.navigate", { url: origin + route });
    await waitFor("document.readyState==='complete'&&Boolean(document.querySelector('.auth-page,.opal-workspace'))", "app_ready");
  } finally { navigating = false; }
}
async function fill(selector, value) {
  currentStep='fill_control';
  await evaluate(`(()=>{const el=document.querySelector(${quote(selector)});if(!el||el.disabled)throw Error();el.focus();const prototype=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(prototype,'value').set.call(el,${quote(value)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
}
async function click(selector) {
  currentStep='click_control';
  await evaluate(`(()=>{const el=[...document.querySelectorAll(${quote(selector)})].find(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]'));if(!el||el.disabled)throw Error();el.focus();el.click();return true})()`);
}
async function clickText(text, selector = "button,a") {
  currentStep='click_named_control';
  await evaluate(`(()=>{const el=[...document.querySelectorAll(${quote(selector)})].find(el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')&&el.textContent.trim()===${quote(text)});if(!el||el.disabled)throw Error();el.focus();el.click();return true})()`);
}
async function screenshot(name) {
  const { data } = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  if (data.length > 12 * 1024 * 1024) throw new Error("screenshot_bound");
  const file = path.join(artifacts, `${name}.png`); await writeFile(file, Buffer.from(data, "base64")); screenshots.push({ name, file });
}
async function signIn(password = PASSWORD) {
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('[data-testid=password-auth-submit]').disabled", "login_ready");
  await fill("#auth-email", EMAIL); await fill("#auth-password", password); await click("[data-testid=password-auth-submit]");
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "password_authenticated");
  assert.equal(await evaluate("document.querySelector('.opal-workspace').dataset.uiShell"), EXPECTED_SHELL, "real_authenticated_shell_must_match_operator_build");
}
async function logout() {
  await accountAction({ evaluate, click, clickText, waitFor }, 'Sign out');
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('.opal-workspace')", "logout_confirmed");
}
async function submitProof(password) {
  await waitFor("Boolean(document.querySelector('#auth-password'))&&!document.querySelector('#auth-password').disabled", "proof_ready");
  await fill("#auth-password", password); await fill("#auth-password-confirm", password); await click("[data-testid=password-auth-submit]");
}
async function mailbox(purpose) {
  const result = await bridge.send("mailbox", { purpose });
  assert.equal(result.found, true, "synthetic_mail_missing");
  if (purpose === "password_changed") return result;
  assert.match(result.proof ?? "", /^[A-Za-z0-9_-]{43}$/, "synthetic_proof_shape");
  proofValues.push(result.proof); sensitiveValues.add(result.proof); return result.proof;
}
function rememberResponseSecrets(result) {
  const remember = (value) => { if (typeof value === "string" && value.length >= 20 && value.length <= 1024 && sensitiveValues.size < 1024) sensitiveValues.add(value); };
  try { const value = JSON.parse(Buffer.from(result.bodyBase64 || "", "base64").toString("utf8")); remember(value.csrf_token); remember(value.nonce); } catch { /* Non-JSON/empty responses contain no structured token. */ }
  for (const [name, value] of result.headers) if (name.toLowerCase() === "set-cookie") remember(value.split(";", 1)[0].split("=").slice(1).join("="));
}
async function rawRequest(method, pathname, body = null, headers = {}) {
  return evaluate(`(async()=>{const response=await fetch(${quote(pathname)},{method:${quote(method)},credentials:'same-origin',cache:'no-store',redirect:'error',headers:${quote({ ...(body ? { "Content-Type": "application/json" } : {}), ...headers })},${body ? `body:${quote(JSON.stringify(body))},` : ""}});const text=await response.text();return {status:response.status,body:text.length<=16384?text:null}})()`);
}
async function assertNoProofPersistence(label) {
  await check(label, `(()=>{const values=[location.href,document.documentElement.outerHTML,document.cookie,...Object.values(localStorage),...Object.values(sessionStorage)];return !values.some(value=>${quote(proofValues)}.some(proof=>value.includes(proof)))})()`);
}
async function advanceAdmissionWindow() {
  // Explicit scenario boundary only: never retry an unexpected rate denial.
  // The bridge leaves mailbox cooldowns and daily mail quotas untouched.
  await bridge.send("recover_rates"); fixtureClockSteps++;
}

try {
  // The executable/argv identify only the reviewed local test bridge. No shell,
  // remote host or production credentials are hardcoded or inferred here.
  const executable = process.env.AQUA_P05_BRIDGE_EXECUTABLE;
  const argv = JSON.parse(process.env.AQUA_P05_BRIDGE_ARGS_JSON || "[]");
  assert.ok(executable && path.isAbsolute(executable), "bridge_executable_required");
  assert.ok(Array.isArray(argv) && argv.length > 0 && argv.length <= 12 && argv.every((arg) => typeof arg === "string" && arg.length < 1024), "bridge_argv_required");
  const files = new Map(); let bytes = 0;
  async function preload(directory, prefix = "") {
    for (const item of await readdir(directory, { withFileTypes: true })) {
      const file = path.join(directory, item.name), key = `${prefix}/${item.name}`;
      if ((await lstat(file)).isSymbolicLink()) throw new Error("dist_symlink_rejected");
      if (item.isDirectory()) await preload(file, key);
      else if (item.isFile()) { const data = await readFile(file); bytes += data.length; if (data.length > 8 * 1024 * 1024 || bytes > 32 * 1024 * 1024 || files.size >= 300) throw new Error("dist_bound"); files.set(key, data); }
    }
  }
  if ((await lstat(distRoot)).isSymbolicLink() || !(await lstat(distRoot)).isDirectory()) throw new Error("dist_root_rejected");
  await preload(distRoot); assert.ok(files.has("/index.html"), "production_build_required");
  loadedAssets = [...files].filter(([name]) => name !== "/50x.html").map(([name, bytes]) => ({ name, sha256: createHash("sha256").update(bytes).digest("hex") }));
  await ensureArtifacts();
  server = createServer((request, response) => {
    if (++staticCount > MAX_REQUESTS || performance.now() - started > MAX_MS || request.method !== "GET") { response.writeHead(503); response.end(); return; }
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    if (pathname.startsWith("/api/")) { response.writeHead(500); response.end(); return; }
    const key = files.has(pathname) ? pathname : !path.extname(pathname) ? "/index.html" : null;
    if (!key) { response.writeHead(pathname === "/favicon.ico" ? 204 : 404); response.end(); return; }
    const type = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".woff2": "font/woff2" }[path.extname(key)] || "application/octet-stream";
    response.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff" }); response.end(files.get(key));
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve)); origin = `http://127.0.0.1:${server.address().port}`;
  bridge = new FixtureBridge(executable, argv, origin);
  const ready = await bridge.ready;
  assert.equal(ready.schema_version, 5, "schema5_fixture_required");
  assert.equal(ready.origin, origin, "exact_loopback_origin_required");
  assert.equal(ready.dataset_grants, 0, "ungranted_fixture_account_required");
  assert.equal(ready.workspace_analysis_fixture === true, analysisFixture, "explicit_analysis_fixture_mode_required");
  if (analysisFixture) assert.equal(ready.capabilities?.workspace_analysis, true, "analysis_fixture_capability_required");
  assert.equal(ready.network, "none", "isolated_backend_network_required");
  assert.equal(ready.database_transport, "private_unix_socket", "isolated_database_required");
  const temporaryRoot = await realpath(tmpdir()); profile = await mkdtemp(path.join(temporaryRoot, "aqua-p05-real-browser-"));
  const env = Object.fromEntries(["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "APPDATA", "HOME"].filter((name) => process.env[name]).map((name) => [name, process.env[name]]));
  const chromeExecutable = process.env.AQUA_CHROME_EXECUTABLE || (process.platform === "win32" ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" : "/usr/bin/google-chrome");
  browser = spawn(chromeExecutable, ["--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-extensions", "--disable-default-apps", "--no-pings", "--metrics-recording-only", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--remote-debugging-pipe", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"], env });
  cdp = new BrowserPipe(browser, { session: () => sessionId, deadline: started + MAX_MS });
  deadline = setTimeout(() => cdp.fail("browser_suite_deadline"), Math.max(1, MAX_MS - (performance.now() - started)));
  const version = await cdp.ready(); const targets = await cdp.send("Target.getTargets");
  ({ sessionId } = await cdp.send("Target.attachToTarget", { targetId: targets.targetInfos.find((item) => item.type === "page").targetId, flatten: true }));
  cdp.onEvent = (event) => {
    if (event.sessionId !== sessionId) return;
    if (event.method === "Network.loadingFailed" && event.params.canceled && abortedNetworkRequests.size < MAX_REQUESTS) abortedNetworkRequests.add(event.params.requestId);
    if (event.method === "Runtime.exceptionThrown") browserErrors.push("runtime_exception");
    if (event.method === "Runtime.consoleAPICalled" && [...sensitiveValues].some((secret) => JSON.stringify(event.params.args).includes(secret))) consoleLeaks++;
    if (event.method !== "Fetch.requestPaused") return;
    const wasNavigating = navigating;
    void (async () => {
      const { requestId, request } = event.params, url = new URL(request.url);
      if (++requests > MAX_REQUESTS || performance.now() - started > MAX_MS) throw new Error("request_bound");
      if (url.origin === origin && url.pathname.startsWith("/api/")) {
        apiRequests++;
        const body = request.postData || ""; if (Buffer.byteLength(body) > MAX_BODY) throw new Error("request_body_bound");
        const result = await bridge.send("request", { method: request.method, path: url.pathname + url.search, headers: Object.entries(request.headers), bodyBase64: Buffer.from(body).toString("base64") });
        assert.ok(Number.isInteger(result.status) && result.status >= 100 && result.status <= 599 && Array.isArray(result.headers), "bridge_response_shape");
        apiOutcomes.push({ method: request.method, path: url.pathname, status: result.status });
        const encoded = result.bodyBase64 || ""; if (Buffer.from(encoded, "base64").length > MAX_BODY) throw new Error("response_body_bound");
        rememberResponseSecrets(result);
        await cdp.send("Fetch.fulfillRequest", { requestId, responseCode: result.status, responseHeaders: result.headers.map(([name, value]) => ({ name, value })), ...(result.status === 204 ? {} : { body: encoded }) });
      } else if (url.origin === origin && request.method === "GET") await cdp.send("Fetch.continueRequest", { requestId });
      else { external++; await cdp.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }); }
    })().catch((error) => {
      if (error.shutdownSessionMissing && cdp.stopping) canceled++;
      else if (error.canceled && (wasNavigating || navigating || abortedNetworkRequests.has(event.params.networkId))) canceled++;
      else protocolErrors.push(error instanceof assert.AssertionError ? "bridge_contract_assertion" : error.message);
    });
  };
  await cdp.send("Page.enable"); await cdp.send("Network.enable"); await cdp.send("Runtime.enable");
  await cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: `(()=>{let config;window.google={accounts:{id:{initialize(value){config=value},disableAutoSelect(){},renderButton(parent){const button=document.createElement('button');button.type='button';button.textContent='Continue with Google';button.dataset.testid='fixture-google-button';button.onclick=()=>config.callback({credential:JSON.stringify({nonce:config.nonce})});parent.append(button)}}}}})();` });
  await cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });

  await navigate("/register"); await waitFor("!document.querySelector('#auth-email').disabled", "registration_ready");
  await fill("#auth-email", EMAIL); await click("[data-testid=password-auth-submit]");
  await waitFor("location.pathname==='/registration-sent'", "actual_registration_ack");
  const verification = await mailbox("verify_email");
  await navigate(`/verify-email#token=${verification}`); await assertNoProofPersistence("actual email proof is consumed only into page memory");
  await submitProof(PASSWORD); await waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", "actual_verification_success");
  await check("real verification creates no automatic browser session", "!document.querySelector('.opal-workspace')");
  await evaluate("localStorage.setItem('VITE_AQUA_UI_SHELL','attacker-choice');localStorage.setItem('aqua-ui-shell','attacker-choice');localStorage.setItem('VITE_AQUA_DEMO_MODE','true')");
  await navigate("/signin?VITE_AQUA_UI_SHELL=attacker-choice&shell=attacker-choice&demo=true#legacy");
  await check("hostile client flags cannot replace actual backend sign-in", "location.search===''&&location.hash===''&&!document.querySelector('.opal-workspace')&&Boolean(document.querySelector('#auth-password'))");
  await assertLoginDelivery(check); performanceSamples.push(await capturePerformance(evaluate, "actual-desktop-signin"));
  await signIn(); await assertShell(check);
  await evaluate("localStorage.removeItem('VITE_AQUA_UI_SHELL');localStorage.removeItem('aqua-ui-shell');localStorage.removeItem('VITE_AQUA_DEMO_MODE')");
  await check("new password account has personal UI without dataset access", "document.querySelector('.opal-composer textarea').disabled&&document.body.textContent.includes('Access pending')");
  const me = await rawRequest("GET", "/api/auth/me"); assert.equal(me.status, 200, "real_session_cookie_round_trip");
  const session = JSON.parse(me.body); assert.equal(session.can_query, false, "new_account_has_no_dataset_grant");
  firstAccountWorkspace = await actualPersonalWorkspace({ check, click, clickText, fill, waitFor, evaluate, navigate, rawRequest, screenshot, csrf: session.csrf_token });
  const query = await rawRequest("POST", "/api/query", { question: "Synthetic dataset-denial check" }, { "X-CSRF-Token": session.csrf_token });
  assert.equal(query.status, 403, "real_dataset_permission_denial"); results.push({ check: "actual API rejects a query from a no-dataset account", passed: true });
  if (analysisFixture) firstAccountWorkspace.chatId = await actualAnalysisWorkspace({ check, click, clickText, fill, waitFor, evaluate, navigate, rawRequest, bridge, screenshot, csrf: session.csrf_token,
    recoverAnalysisRates: async () => { await bridge.send("workspace_recover_analysis_rate"); analysisClockSteps++; },
    queryCount: () => apiOutcomes.filter((call) => call.method === "POST" && /^\/api\/v1\/chats(?:\/[^/]+\/messages(?:\/[^/]+\/retries)?)?$/.test(call.path)).length });
  await accountAction({ evaluate, click, clickText, waitFor }, 'Settings');
  await check("actual signed-in account can reach its own Settings", `document.querySelector('.settings-shell').textContent.includes(${quote(EMAIL)})`);
  await screenshot("actual-password-account-settings"); await clickText("Back to workspace");
  await logout(); assert.equal((await rawRequest("GET", "/api/auth/me")).status, 401, "actual_logout_revokes_session");
  results.push({ check: "actual logout removes the authenticated server session", passed: true });
  await navigate(`/verify-email#token=${verification}`); await submitProof(PASSWORD);
  await waitFor("document.querySelector('h1')?.textContent==='Request a new link'", "actual_used_proof_rejected");
  results.push({ check: "actual spent verification proof cannot be replayed", passed: true });

  await advanceAdmissionWindow();
  await navigate("/signin"); await signIn();
  const beforeReset = await rawRequest("GET", "/api/auth/me"); const oldCsrf = JSON.parse(beforeReset.body).csrf_token;
  // Capture one old HttpOnly cookie in process memory solely to verify that the
  // real backend rejects it after reset; never serialize it into evidence.
  const oldCookies = (await cdp.send("Network.getCookies", { urls: [origin] })).cookies;
  const oldSessionCookies = oldCookies.filter((cookie) => ["aqua_session", "__Host-aqua_session"].includes(cookie.name));
  assert.equal(oldSessionCookies.length, 1, "single_session_cookie_required");
  assert.ok(oldSessionCookies[0].httpOnly && oldSessionCookies[0].path === "/" && oldSessionCookies[0].sameSite === "Lax", "session_cookie_security_attributes");
  await navigate("/forgot-password"); await waitFor("!document.querySelector('#auth-email').disabled", "reset_request_ready");
  await fill("#auth-email", EMAIL); await click("[data-testid=password-auth-submit]");
  await waitFor("location.pathname==='/check-email'", "actual_reset_ack");
  const reset = await mailbox("reset_password");
  await navigate(`/reset-password#token=${reset}`); await assertNoProofPersistence("actual reset bearer stays out of URL DOM and storage");
  await submitProof(NEXT_PASSWORD); await waitFor("document.querySelector('h1')?.textContent==='Password updated'", "actual_reset_success");
  await mailbox("password_changed");
  const oldCookie = oldSessionCookies.map(({ name, value }) => `${name}=${value}`).join("; ");
  const revoked = await bridge.send("request", { method: "GET", path: "/api/auth/me", headers: [["Cookie", oldCookie]], bodyBase64: "" });
  assert.equal(revoked.status, 401, "old_session_revoked_after_reset");
  const revokedQuery = await bridge.send("request", { method: "POST", path: "/api/query", headers: [["Cookie", oldCookie], ["Origin", origin], ["X-CSRF-Token", oldCsrf], ["Content-Type", "application/json"]], bodyBase64: Buffer.from(JSON.stringify({ question: "Synthetic revoked-session query" })).toString("base64") });
  assert.equal(revokedQuery.status, 401, "old_session_cannot_query_after_reset");
  results.push({ check: "actual password reset revokes previously issued server sessions", passed: true });
  await navigate(`/reset-password#token=${reset}`); await submitProof(NEXT_PASSWORD); await waitFor("document.querySelector('h1')?.textContent==='Request a new link'", "actual_reset_replay_rejected");
  // Deliberately exhaust the shared challenge budget, then observe real-time
  // recovery. Never shorten the server window or reinterpret a 429 as a 401.
  let exhausted = false;
  for (let attempt = 0; attempt < 11; attempt++) {
    const response = await rawRequest("GET", "/api/auth/config");
    if (response.status === 429) { exhausted = true; break; }
    assert.equal(response.status, 200, "challenge_budget_unexpected_status");
  }
  assert.equal(exhausted, true, "bounded_challenge_budget_required");
  await navigate("/signin");
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('[data-testid=password-auth-submit]').disabled", "post_reset_login_ready");
  await fill("#auth-email", EMAIL); await fill("#auth-password", PASSWORD); await click("[data-testid=password-auth-submit]");
  await waitFor("document.querySelector('[data-testid=password-auth-error]')?.textContent.includes('Too many attempts')", "actual_bootstrap_rate_denial");
  const passwordPosts = () => apiOutcomes.filter((entry) => entry.method === "POST" && entry.path === "/api/v1/auth/password-login").length;
  const beforeCooldown = passwordPosts();
  await check("real exhausted bootstrap budget disables login and clears its password", "document.querySelector('[data-testid=password-auth-submit]').disabled&&document.querySelector('#auth-password').value===''");
  await waitFor("!document.querySelector('[data-testid=password-auth-submit]').disabled", "natural_retry_after_expired", 70000);
  assert.equal(passwordPosts(), beforeCooldown, "cooldown_must_not_retry_login_automatically");
  results.push({ check: "real rate window recovers naturally with zero automatic password retries", passed: true });
  await fill("#auth-email", EMAIL); await fill("#auth-password", PASSWORD); await click("[data-testid=password-auth-submit]");
  await waitFor("Boolean(document.querySelector('[data-testid=password-auth-error]'))", "old_password_rejected");
  await waitFor("document.querySelector('[data-testid=password-auth-error]')?.textContent.includes('We couldn’t verify')", "actual_old_password_401");
  assert.ok(apiOutcomes.some((entry) => entry.path === "/api/v1/auth/password-login" && entry.status === 401), "old_password_requires_actual_401");
  await check("old password fails with safe generic feedback after reset", "document.querySelector('#auth-password').value===''&&!document.querySelector('.opal-workspace')");
  await signIn(NEXT_PASSWORD); await logout();
  results.push({ check: "new password works after reset while reset proof remains one-use", passed: true });

  await advanceAdmissionWindow(); await navigate("/signin");
  await waitFor("Boolean(document.querySelector('[data-testid=fixture-google-button]'))", "actual_google_config_ready");
  const configResponse = await rawRequest("GET", "/api/auth/config"); assert.equal(configResponse.status, 200);
  const config = JSON.parse(configResponse.body);
  const forged = await rawRequest("POST", "/api/auth/google", { credential: JSON.stringify({ nonce: config.nonce }) }, { "X-CSRF-Token": "synthetic-forged-csrf" });
  assert.equal(forged.status, 403, "actual_google_rejects_forged_csrf");
  assert.equal((await rawRequest("GET", "/api/auth/me")).status, 401, "forged_csrf_creates_no_session");
  await navigate("/signin"); await waitFor("Boolean(document.querySelector('[data-testid=fixture-google-button]'))", "fresh_google_config");
  await click("[data-testid=fixture-google-button]"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "actual_google_login");
  await assertShell(check);
  const googleSession = await rawRequest("GET", "/api/auth/me");
  await foreignPersonalWorkspace({ check, rawRequest, workspace: firstAccountWorkspace, csrf: JSON.parse(googleSession.body).csrf_token });
  results.push({ check: "actual Google handler rejects forged CSRF then accepts a fresh legitimate nonce flow", passed: true });
  await screenshot("actual-google-no-dataset-workspace"); await logout();
  await assertNoProofPersistence("final browser state contains no captured proof values");
  assert.equal(external, 0, "external_request_blocked"); assert.equal(consoleLeaks, 0, "console_secret_leak");
  assert.deepEqual(browserErrors, [], "uncaught_browser_error"); assert.deepEqual(protocolErrors, [], "browser_bridge_protocol_failure");
  results.push({ check: "actual browser/API journeys use bounded local traffic without provider calls", passed: true });
  await writeFile(path.join(artifacts, "browser-version.json"), JSON.stringify({ browser: version.product }, null, 2) + "\n");
} catch (error) {
  failureStep=/^[A-Za-z0-9 _.,:&()-]{1,180}$/.test(currentStep)?currentStep:'unclassified_step';
  failure = error instanceof assert.AssertionError ? error.message.split("\n")[0] : String(error.message || "real_browser_gate_failed");
  failureDiagnostic = error.browserDiagnostic ?? cdp?.diagnostic ?? null;
  if (sessionId) await screenshot("failure-current-view").catch(() => {});
} finally {
  clearTimeout(deadline);
  if (cdp) await cdp.stop();
  if (!failure && cdp?.cleanupFailure) failure = "browser_cleanup_failed";
  if (bridge?.finished) bridgeCleanup = bridge.finished;
  if (bridge && bridge.process.exitCode === null) {
    if (!bridge.finished) {
      try { bridgeCleanup = await bridge.send("finish", {}, 30000); } catch { bridgeCleanup = bridge.finished || { status: "unconfirmed" }; }
    }
    bridge.process.stdin.end(); await Promise.race([bridge.closed, delay(3000)]);
    if (bridge.process.exitCode === null) bridge.process.kill();
    if (bridge.finished) bridgeCleanup = bridge.finished;
  }
  server?.closeAllConnections(); if (server?.listening) await new Promise((resolve) => server.close(resolve));
  if (profile) {
    const root = await realpath(tmpdir()), resolved = await realpath(profile);
    assert.equal(path.dirname(resolved), root); assert.ok(path.basename(resolved).startsWith("aqua-p05-real-browser-")); assert.equal((await lstat(profile)).isSymbolicLink(), false);
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
}
await ensureArtifacts();
const backendRemoved = bridgeCleanup?.report?.cleanup === "removed_and_absence_confirmed" && Array.isArray(bridgeCleanup?.report?.remaining_ids) && bridgeCleanup.report.remaining_ids.length === 0;
const backendPassed = bridgeCleanup?.status === "passed" && bridgeCleanup?.report?.status === "passed";
if (!failure && protocolErrors.length) failure = "browser_bridge_protocol_failure";
const backendReport = Object.fromEntries(["run", "status", "step", "cleanup", "remaining_ids", "worker_exit", "failure", "worker_error"].filter((key) => Object.hasOwn(bridgeCleanup?.report ?? {}, key)).map((key) => [key, bridgeCleanup.report[key]]));
if (!failure && (!backendRemoved || !backendPassed)) failure = "backend_cleanup_unconfirmed";
// Only explicitly sanitized bridge cleanup fields are persisted. Mail payloads,
// cookies, credentials, CSRF values and proof links never enter the report.
const report = { status: failure ? "failed" : "passed", failure, failure_step:failureStep, last_completed_check:results.at(-1)?.check||null, checked_utc: new Date().toISOString(), mode: "real_fastapi_disposable_postgres_browser",
  expected_shell: EXPECTED_SHELL, analysis_fixture: analysisFixture, browser_diagnostic: failureDiagnostic ?? cdp?.diagnostic ?? null, bridge_diagnostic: bridge?.diagnostic ?? null, loadedAssets, results, screenshots, performanceSamples, observations: { requests, apiRequests, external_attempts: external, consoleLeaks, browserErrors, protocolErrors, canceled, explicit_fixture_admission_clock_steps: fixtureClockSteps, explicit_fixture_analysis_clock_steps: analysisClockSteps, apiOutcomes },
  cleanup: { browser_stopped: !browser || cdp?.stopped === true, temporary_profile_removed: Boolean(profile), loopback_closed: !server?.listening, backend_status: bridgeCleanup?.status ?? null, backend_resources_removed: backendRemoved, backend_report: backendReport },
  elapsed_seconds: Math.round((performance.now() - started) / 10) / 100,
  limitations: ["Real FastAPI/auth/database code against synthetic disposable fixtures; no deployed origin or production data validation.", "Google verifier and email sender are synthetic test adapters; no Google or email provider contacted.", "No analytical database or AI model is exercised."] };
await writeFile(path.join(artifacts, "report.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify({ status: report.status, checks: results.length, failure, browser_diagnostic: report.browser_diagnostic, bridge_diagnostic: report.bridge_diagnostic, backend_cleanup: backendReport, report: path.join(artifacts, "report.json") }));
if (failure || !report.cleanup.browser_stopped || !report.cleanup.loopback_closed || report.cleanup.backend_status !== "passed") process.exitCode = 1;
