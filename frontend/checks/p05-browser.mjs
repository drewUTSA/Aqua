// Production-build browser gate, exclusively against synthetic intercepted APIs.
// Run after `npm run build`; no application backend, Google or mail service runs.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, realpath, lstat, rm, readFile, readdir, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";
import { makeFixture, GOOGLE_STUB, EMAIL_A, EMAIL_B, PASSWORD, VERIFY_PROOF, RESET_PROOF } from "./p05-browser-fixture.mjs";
import { EXPECTED_SHELL, assertShell, assertLoginDelivery, capturePerformance, assertEssentialControls, assertSafeAreaStyles, enlargeText, captureControlBounds } from "./p05-shell-browser-checks.mjs";

const MAX_MS = 240000, MAX_REQUESTS = 900, MAX_API = 180, MAX_PROTOCOL_BYTES = 16 * 1024 * 1024;
const started = performance.now();
const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
function configuredPath(name, fallback) {
  const value = process.env[name] || fallback;
  if (value.length > 4096 || value.includes("\0") || !path.isAbsolute(value)) throw new Error("artifact_path_invalid");
  return path.resolve(value);
}
const artifacts = configuredPath("AQUA_P05_ARTIFACT_DIR", path.resolve(frontend, "../../browser-evidence"));
const distRoot = configuredPath("AQUA_P05_DIST", path.join(frontend, "dist"));
let loadedAssets = [];
async function ensureArtifacts() {
  await mkdir(artifacts, { recursive: true });
  if ((await lstat(artifacts)).isSymbolicLink()) throw new Error("artifact_directory_symlink_rejected");
}
const temporaryRoot = await realpath(tmpdir());
const fixture = makeFixture();
const results = [], screenshots = [], external = [], protocolFailures = [], performanceSamples = [], scrollObservations = [];
const sessions = new Set(), fonts = [], transitions = new Set(), closingSessions = new Set();
let browser, cdp, profile, server, sessionId, origin, closed, deadline;
let requestCount = 0, staticRequests = 0, apiRequests = 0, consoleLeaks = 0, runtimeErrors = 0, canceledInterceptions = 0, cleanup = false;
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const escaped = (value) => JSON.stringify(value);

class PipeClient {
  constructor(child) {
    this.child = child; this.pending = new Map(); this.sequence = 0; this.buffer = Buffer.alloc(0); this.onEvent = () => {};
    child.stdio[4].on("data", (chunk) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      if (this.buffer.length > MAX_PROTOCOL_BYTES) { this.fail(); child.kill(); return; }
      let end;
      while ((end = this.buffer.indexOf(0)) !== -1) {
        const raw = this.buffer.subarray(0, end); this.buffer = this.buffer.subarray(end + 1);
        if (!raw.length) continue;
        let message;
        try { message = JSON.parse(raw.toString("utf8")); } catch { this.fail(); child.kill(); return; }
        const task = this.pending.get(message.id);
        if (task) {
          clearTimeout(task.timer); this.pending.delete(message.id);
          if (message.error) {
            const detail = String(message.error.message ?? "");
            const error = new Error("browser_protocol_failed");
            error.protocolReason = /Invalid InterceptionId|No resource with given identifier/.test(detail) ? "request_no_longer_exists"
              : /Session with given id not found|Target closed|Session closed/.test(detail) ? "target_no_longer_exists" : "other_protocol_error";
            task.reject(error);
          } else task.resolve(message.result);
        } else this.onEvent(message);
      }
    });
    child.once("error", () => this.fail()); child.once("exit", () => this.fail());
  }
  fail() { for (const task of this.pending.values()) { clearTimeout(task.timer); task.reject(new Error("browser_closed")); } this.pending.clear(); }
  send(method, params = {}, target = sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("browser_protocol_deadline")); }, 7000);
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdio[3].write(JSON.stringify({ id, method, params, ...(target ? { sessionId: target } : {}) }) + "\0");
    });
  }
}

async function preload() {
  const files = new Map(); let bytes = 0;
  if ((await lstat(distRoot)).isSymbolicLink() || !(await lstat(distRoot)).isDirectory()) throw new Error("dist_root_rejected");
  async function visit(directory, prefix = "") {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      const full = path.join(directory, entry.name), relative = `${prefix}/${entry.name}`;
      if ((await lstat(full)).isSymbolicLink()) throw new Error("dist_symlink_rejected");
      if (entry.isDirectory()) await visit(full, relative);
      else if (entry.isFile()) {
        const data = await readFile(full); bytes += data.length;
        if (data.length > 8 * 1024 * 1024 || bytes > 32 * 1024 * 1024 || files.size >= 300) throw new Error("dist_budget_exceeded");
        files.set(relative, data);
      }
    }
  }
  await visit(distRoot);
  assert.ok(files.has("/index.html"), "production_dist_required");
  loadedAssets = [...files].filter(([name]) => name !== "/50x.html").map(([name, bytes]) => ({ name, sha256: createHash("sha256").update(bytes).digest("hex") }));
  return files;
}

async function evaluate(expression) {
  const value = await cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (value.exceptionDetails) throw new Error("page_evaluation_failed");
  return value.result.value;
}
async function waitFor(expression, label, milliseconds = 5500) {
  const stop = performance.now() + milliseconds;
  while (performance.now() < stop) { if (await evaluate(expression)) return; await delay(40); }
  throw new Error(`condition_failed:${label}`);
}
async function check(label, expression) {
  assert.equal(await evaluate(expression), true, label);
  results.push({ check: label, passed: true });
}
const visibleFunction = `(el)=>Boolean(el&&el.getClientRects().length&&!el.closest('[hidden],[inert]'))`;
async function click(selector) {
  const expression = `(()=>{const el=[...document.querySelectorAll(${escaped(selector)})].find(${visibleFunction});if(!el||el.disabled)throw Error('control_missing');el.click();return true})()`;
  await evaluate(expression);
}
async function clickText(text, selector = "button,a") {
  await evaluate(`(()=>{const el=[...document.querySelectorAll(${escaped(selector)})].find(el=>(${visibleFunction})(el)&&el.textContent.trim()===${escaped(text)});if(!el||el.disabled)throw Error('control_missing');el.click();return true})()`);
}
async function fill(selector, value) {
  await evaluate(`(()=>{const el=document.querySelector(${escaped(selector)});if(!el||el.disabled)throw Error('field_missing');el.focus();const proto=el.tagName==='TEXTAREA'?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(proto,'value').set.call(el,${escaped(value)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true})()`);
}
async function key(key, modifiers = 0, text) {
  const code = { Enter: 13, Escape: 27, Tab: 9, ArrowDown: 40, ArrowUp: 38 }[key];
  await cdp.send("Input.dispatchKeyEvent", { type: "keyDown", key, code: key, windowsVirtualKeyCode: code, modifiers, ...(text ? { text } : {}) });
  await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key, code: key, windowsVirtualKeyCode: code, modifiers });
}
async function viewport(width, height, mobile = false) {
  await cdp.send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
  await delay(70);
}
async function navigate(route = "/signin") {
  // Email links enter a new document; avoid Page.navigate treating only a proof
  // fragment as a same-document update of a previously completed form.
  transitions.add(sessionId);
  try {
    await cdp.send("Page.navigate", { url: "about:blank" });
    await waitFor("location.href==='about:blank'", "navigation_reset");
    await cdp.send("Page.navigate", { url: origin + route });
    await waitFor("document.readyState==='complete' && Boolean(document.querySelector('.auth-page,.opal-workspace,.not-found,.legal-page'))", "page_ready");
  } finally { transitions.delete(sessionId); }
}
async function screenshot(name) {
  const { data } = await cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
  if (data.length > 12 * 1024 * 1024) throw new Error("screenshot_budget_exceeded");
  const destination = path.join(artifacts, `${name}.png`);
  await writeFile(destination, Buffer.from(data, "base64"));
  screenshots.push({ name, file: destination });
}
async function signIn(email = EMAIL_A) {
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('[data-testid=password-auth-submit]').disabled", "login_ready");
  await fill("#auth-email", email); await fill("#auth-password", PASSWORD);
  await click("[data-testid=password-auth-submit]");
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "workspace_open");
  assert.equal(await evaluate("document.querySelector('.opal-workspace').dataset.uiShell"), EXPECTED_SHELL, "authenticated_shell_must_match_operator_build");
}
async function legalRoundTrip(state) {
  const requestsBefore = fixture.calls.length;
  await click("a[href='/privacy']");
  await waitFor("location.pathname==='/privacy'&&Boolean(document.querySelector('[data-testid=legal-page]'))", "locked_privacy_route");
  await check(`${state} logout keeps the same private workspace locked during Privacy`, "document.querySelector('.opal-workspace')===window.__fixtureRetainedWorkspace&&Boolean(document.querySelector('.opal-workspace[hidden][inert]'))&&document.querySelector('.opal-workspace textarea').value==='Account A private unsent fixture'&&!document.body.innerText.includes('Account A private unsent fixture')");
  await click(".legal-page__nav a[href='/terms']");
  await waitFor("location.pathname==='/terms'&&document.querySelector('#legal-heading')?.textContent==='Terms of Service'", "locked_terms_route");
  await clickText("Back to AQUA");
  await waitFor("location.pathname==='/'&&Boolean(document.querySelector('.auth-page'))", "locked_workspace_return");
  await check(`${state} logout survives Terms and Back without remounting or revealing a draft`, "document.querySelector('.opal-workspace')===window.__fixtureRetainedWorkspace&&Boolean(document.querySelector('.opal-workspace[hidden][inert]'))&&document.querySelector('.opal-workspace textarea').value==='Account A private unsent fixture'&&!document.body.innerText.includes('Account A private unsent fixture')");
  assert.equal(fixture.calls.length, requestsBefore, "legal_navigation_cannot_restart_auth_or_query");
}
async function menu(action) {
  await click(".workspace-header [aria-label='Account menu']");
  await clickText(action, "[role=menuitem]");
}
async function proofSubmission() {
  await waitFor("Boolean(document.querySelector('#auth-password'))&&!document.querySelector('#auth-password').disabled", "proof_form_ready");
  await fill("#auth-password", PASSWORD); await fill("#auth-password-confirm", PASSWORD);
  await click("[data-testid=password-auth-submit]");
}
async function noBearerLeak(label) {
  await check(label, `(()=>{const values=[location.href,document.documentElement.outerHTML,document.cookie,...Object.values(localStorage),...Object.values(sessionStorage)];return !values.some(value=>[${escaped(VERIFY_PROOF)},${escaped(RESET_PROOF)}].some(proof=>value.includes(proof)))})()`);
}
async function captureFonts(view) {
  const selectors = ["html", "body", ".opal-workspace", ".auth-page", "textarea", "input"];
  const computed = await evaluate(`Object.fromEntries(${escaped(selectors)}.map(selector=>{const el=document.querySelector(selector);return [selector,el?getComputedStyle(el).fontFamily:null]}))`);
  await cdp.send("DOM.enable"); await cdp.send("CSS.enable");
  const { root } = await cdp.send("DOM.getDocument");
  const platform = {};
  for (const selector of selectors) {
    const { nodeId } = await cdp.send("DOM.querySelector", { nodeId: root.nodeId, selector });
    if (nodeId) platform[selector] = (await cdp.send("CSS.getPlatformFontsForNode", { nodeId })).fonts.map(({ familyName, isCustomFont, glyphCount }) => ({ familyName, isCustomFont, glyphCount }));
  }
  fonts.push({ view, computed, platform });
  await writeFile(path.join(artifacts, "font-diagnostics.json"), JSON.stringify(fonts, null, 2) + "\n");
}
async function preparePage() {
  sessions.add(sessionId);
  await cdp.send("Page.enable"); await cdp.send("Network.enable"); await cdp.send("Runtime.enable");
  await cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: GOOGLE_STUB });
}

let failure = null, failureLayout = null;
try {
  await ensureArtifacts(); const files = await preload();
  server = createServer((request, response) => {
    staticRequests++;
    if (staticRequests > MAX_REQUESTS || performance.now() - started > MAX_MS || request.method !== "GET") { response.writeHead(503); response.end(); return; }
    const pathname = new URL(request.url, "http://127.0.0.1").pathname;
    if (pathname.startsWith("/api/")) { response.writeHead(500); response.end(); return; }
    const data = files.get(pathname) || (!path.extname(pathname) ? files.get("/index.html") : null);
    if (!data) { response.writeHead(pathname === "/favicon.ico" ? 204 : 404); response.end(); return; }
    const extension = path.extname(files.has(pathname) ? pathname : "/index.html");
    const type = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml", ".png": "image/png", ".webp": "image/webp", ".woff2": "font/woff2" }[extension] || "application/octet-stream";
    response.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Content-Type-Options": "nosniff" }); response.end(data);
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  profile = await mkdtemp(path.join(temporaryRoot, "aqua-p05-browser-"));
  const executable = process.env.AQUA_CHROME_EXECUTABLE || (process.platform === "win32" ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" : "/usr/bin/google-chrome");
  const env = Object.fromEntries(["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "APPDATA", "HOME"].filter((name) => process.env[name]).map((name) => [name, process.env[name]]));
  browser = spawn(executable, ["--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-extensions", "--disable-default-apps", "--disable-client-side-phishing-detection", "--no-pings", "--metrics-recording-only", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--remote-debugging-pipe", `--user-data-dir=${profile}`, "about:blank"], { windowsHide: true, stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"], env });
  closed = new Promise((resolve) => browser.once("exit", resolve)); cdp = new PipeClient(browser);
  deadline = setTimeout(() => browser.kill(), MAX_MS);
  const version = await cdp.send("Browser.getVersion");
  const targets = await cdp.send("Target.getTargets");
  const target = targets.targetInfos.find((item) => item.type === "page"); assert.ok(target, "isolated_page_missing");
  ({ sessionId } = await cdp.send("Target.attachToTarget", { targetId: target.targetId, flatten: true }));
  cdp.onEvent = (event) => {
    if (!sessions.has(event.sessionId)) return;
    if (event.method === "Runtime.exceptionThrown") runtimeErrors++;
    if (event.method === "Runtime.consoleAPICalled") {
      const text = JSON.stringify(event.params.args);
      if ([VERIFY_PROOF, RESET_PROOF, PASSWORD, "fixture-session-csrf", "fixture-action-", "fixture-google-credential"].some((value) => text.includes(value))) consoleLeaks++;
    }
    if (event.method !== "Fetch.requestPaused") return;
    const wasTransitioning = transitions.has(event.sessionId);
    void (async () => {
      const { requestId, request } = event.params; const url = new URL(request.url); requestCount++;
      const targetSession = event.sessionId;
      const reply = (status, body, headers = {}) => cdp.send("Fetch.fulfillRequest", {
        requestId, responseCode: status, responseHeaders: Object.entries({ "Content-Type": "application/json", "Cache-Control": "no-store", ...headers }).map(([name, value]) => ({ name, value })),
        ...(status === 204 ? {} : { body: Buffer.from(JSON.stringify(body ?? {})).toString("base64") })
      }, targetSession).catch(() => {}); // An explicitly aborted held request may no longer exist.
      if (requestCount > MAX_REQUESTS || performance.now() - started > MAX_MS) { await cdp.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }, targetSession); return; }
      if (url.origin === origin && url.pathname.startsWith("/api/")) {
        if (++apiRequests > MAX_API) { await reply(503, {}); return; }
        await fixture.route(request, reply); return;
      }
      if (url.origin === origin && request.method === "GET") { await cdp.send("Fetch.continueRequest", { requestId }, targetSession); return; }
      external.push({ origin: url.origin, method: request.method });
      await cdp.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }, targetSession);
    })().catch((error) => {
      // Chrome can cancel a paused old-document request during a deliberate
      // navigation/tab close. Suppress only that specific lifecycle condition.
      if (["request_no_longer_exists", "target_no_longer_exists"].includes(error.protocolReason)
        && (wasTransitioning || transitions.has(event.sessionId) || closingSessions.has(event.sessionId))) canceledInterceptions++;
      else protocolFailures.push(error.protocolReason || "interception_failed");
    });
  };
  await preparePage();
  await viewport(1440, 900); await navigate();
  await waitFor("Boolean(document.querySelector('[data-testid=fixture-google-button]'))", "google_fixture_ready");
  await assertLoginDelivery(check); performanceSamples.push(await capturePerformance(evaluate, "desktop-signin"));
  await check("labeled autofill-friendly dual login", "document.querySelector('#auth-email').autocomplete==='username' && document.querySelector('#auth-email').type==='email' && document.querySelector('#auth-password').autocomplete==='current-password' && Boolean(document.querySelector('label[for=auth-email]')) && Boolean(document.querySelector('label[for=auth-password]'))");
  await click("[aria-label='Show password']"); await check("password visibility toggle exposes state", "document.querySelector('#auth-password').type==='text'&&document.querySelector('[aria-label=\"Hide password\"]').getAttribute('aria-pressed')==='true'");
  await click("[aria-label='Hide password']"); await screenshot("signin-desktop-1440x900"); await captureFonts("sign-in");
  const rejectedBefore = fixture.count("/api/v1/auth/password-login");
  await fill("#auth-email", EMAIL_A); await fill("#auth-password", "Incorrect fixture password"); await click("[data-testid=password-auth-submit]");
  await waitFor("Boolean(document.querySelector('[data-testid=password-auth-error]'))", "rejected_password_state");
  await check("rejected credentials are generic and password clears", "document.querySelector('[data-testid=password-auth-error]').textContent.includes('email and password')&&document.querySelector('#auth-password').value===''&&!document.body.textContent.includes('private-server')");
  assert.equal(fixture.count("/api/v1/auth/password-login"), rejectedBefore + 1);

  fixture.google = "hold"; await navigate(); await signIn(EMAIL_A);
  await assertShell(check);
  await check("password works during stalled Google configuration", "location.pathname==='/'&&Boolean(document.querySelector('.opal-workspace:not([hidden])'))");
  fixture.google = "ready"; await fixture.release("google");
  await check("chat-only entry has complete composer and no empty visuals", "Boolean(document.querySelector('.opal-composer textarea'))&&Boolean(document.querySelector('[aria-label=\"Send message\"]'))&&!document.querySelector('[role=separator],.visual-pane,[aria-label=Visuals]')");
  await viewport(1440, 980); await screenshot("home-desktop-1440x980"); await captureFonts("workspace");
  performanceSamples.push(await capturePerformance(evaluate, "desktop-workspace"));
  await click(".workspace-header [aria-label='Account menu']"); await key("Escape");
  await check("account menu Escape restores trigger focus", "!document.querySelector('[role=menu][aria-label=\"Your account\"]')&&document.activeElement.getAttribute('aria-label')==='Account menu'");

  const beforeIME = fixture.count("/api/query"); await fill(".opal-composer textarea", "Synthetic IME draft");
  await evaluate("document.querySelector('.opal-composer textarea').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',keyCode:229,isComposing:true,bubbles:true}))");
  await delay(80); assert.equal(fixture.count("/api/query"), beforeIME, "IME must not submit"); results.push({ check: "IME Enter does not submit", passed: true });
  await key("Enter", 8, "\r"); await check("Shift+Enter preserves multiline input", "document.querySelector('.opal-composer textarea').value.includes(String.fromCharCode(10))");
  fixture.queryMessage = Array.from({ length: 24 }, (_, index) => `Synthetic paragraph ${index + 1}: this bounded answer contains only fixture values and helps verify reading position.`).join("\n\n");
  await key("Enter"); await waitFor("document.querySelector('.conversation')?.textContent.includes('Synthetic paragraph 24')", "query_answer");
  await fill(".opal-composer textarea", "Draft preserved through Settings");
  const searchSelector = ".desktop-sidebar .sidebar-search input";
  const searchCalls = fixture.calls.length;
  await check("visit-local chat search has an accessible bounded input", "(()=>{const input=document.querySelector('.desktop-sidebar .sidebar-search input');return input?.maxLength===120&&input.labels?.[0]?.textContent==='Search chats in this visit'})()");
  await fill(searchSelector, "Synthetic IME");
  await check("visit-local title search retains the matching conversation", "document.querySelector('.desktop-sidebar .sidebar-search__status').textContent.includes('1 chat matches')&&Boolean(document.querySelector('.desktop-sidebar button[aria-current=page]'))");
  await fill(searchSelector, "<img src=https://attacker.invalid/x onerror=alert(1)> $(rm -rf /)");
  await check("hostile search is literal and cannot select or submit a conversation", "document.querySelector('.desktop-sidebar .sidebar-search__status').textContent.includes('0 chats match')&&!document.querySelector('.desktop-sidebar button[aria-current=page]')&&document.querySelector('.opal-composer textarea').value==='Draft preserved through Settings'&&document.querySelector('.conversation').textContent.includes('Synthetic paragraph 24')&&window.__fixtureScriptExecuted===0");
  await clickText("Clear chat search");
  await check("clearing local search restores titles without losing the draft", "document.querySelector('.desktop-sidebar .sidebar-search input').value===''&&Boolean(document.querySelector('.desktop-sidebar button[aria-current=page]'))&&document.querySelector('.opal-composer textarea').value==='Draft preserved through Settings'");
  assert.equal(fixture.calls.length, searchCalls, "search_makes_no_api_requests");
  await evaluate("(()=>{const el=document.querySelector('.conversation__scroll');el.scrollTop=80;el.dispatchEvent(new Event('scroll'));return true})()");
  await evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))");
  const scrollBefore = await evaluate("document.querySelector('.conversation__scroll').scrollTop");
  await menu("Settings"); await waitFor("Boolean(document.querySelector('#settings-heading'))", "settings_open");
  await clickText("Back to workspace");
  await check("Settings return preserves draft without new conversation", "document.querySelector('.opal-composer textarea').value==='Draft preserved through Settings'&&document.querySelector('.conversation').textContent.includes('Synthetic paragraph 24')");
  await evaluate("new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(()=>resolve(true))))");
  const scrollAfter = await evaluate("document.querySelector('.conversation__scroll').scrollTop");
  scrollObservations.push({ action: "settings_return", before: scrollBefore, after: scrollAfter });
  assert.ok(Math.abs(scrollAfter - scrollBefore) <= 1, "settings_scroll_preserved");
  results.push({ check: "Settings return preserves conversation scroll", passed: true });
  fixture.nextError = { path: "/api/query", status: 503 }; await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('.conversation'))&&!document.querySelector('[aria-label=\"Stop response\"]')", "query_failure_settled");
  await check("failed query preserves recoverable draft", "document.querySelector('.opal-composer textarea').value==='Draft preserved through Settings'");

  fixture.holdQuery = true; fixture.queryMessage = "STALE_ACCOUNT_A_RESULT"; await click("[aria-label='Send message']");
  await waitFor("Boolean(document.querySelector('[aria-label=\"Stop response\"]'))", "query_held");
  await fill(".opal-composer textarea", "Account A private unsent fixture"); fixture.holdLogout = true;
  await evaluate("(()=>{window.__fixtureRetainedWorkspace=document.querySelector('.opal-workspace');return true})()");
  await menu("Sign out"); await waitFor("Boolean(document.querySelector('.opal-workspace[hidden][inert]'))", "logout_workspace_locked");
  await check("pending logout retains hidden inert account draft", "document.querySelector('.opal-workspace textarea').value==='Account A private unsent fixture'");
  await legalRoundTrip("pending");
  fixture.logoutFailure = true; await fixture.release("logout");
  await waitFor("Boolean(document.querySelector('[data-testid=signout-retry]'))", "logout_retry_visible");
  await check("failed logout preserves locked draft", "Boolean(document.querySelector('.opal-workspace[hidden][inert]'))&&document.querySelector('.opal-workspace textarea').value==='Account A private unsent fixture'");
  await legalRoundTrip("failed");
  await check("failed logout returns to an explicit retry after legal navigation", "Boolean(document.querySelector('[data-testid=signout-retry]'))&&!document.querySelector('.opal-workspace:not([hidden])')");
  fixture.holdLogout = false; fixture.logoutFailure = false; await click("[data-testid=signout-retry]");
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('.opal-workspace')", "logout_confirmed");
  fixture.canQuery = false; await signIn(EMAIL_B); fixture.holdQuery = false; await fixture.release("query");
  await check("confirmed logout and account switch discard old private state", "document.querySelector('.opal-composer textarea').value===''&&!document.body.textContent.includes('Account A private unsent fixture')&&!document.body.textContent.includes('STALE_ACCOUNT_A_RESULT')&&!document.body.textContent.includes('Synthetic paragraph 24')");
  await check("signed-in no-dataset account cannot submit a query", "document.querySelector('.opal-composer textarea').disabled&&document.querySelector('[aria-label=\"Send message\"]').disabled&&document.body.textContent.includes('Access pending')");
  await menu("Settings"); await check("no-dataset account can reach own Settings", `document.querySelector('.settings-shell').textContent.includes(${escaped(EMAIL_B)})`); await clickText("Back to workspace");

  fixture.email = null; fixture.canQuery = true; fixture.google = "error"; await navigate();
  await waitFor("document.body.textContent.includes('Google sign-in is temporarily unavailable')", "google_failed");
  fixture.holdLogin = true; await fill("#auth-email", EMAIL_A); await fill("#auth-password", PASSWORD);
  const loginBefore = fixture.count("/api/v1/auth/password-login");
  await evaluate("(()=>{const button=document.querySelector('[data-testid=password-auth-submit]');button.click();button.click();return true})()");
  await waitFor("document.querySelector('[data-testid=password-auth-submit]').disabled", "login_pending"); await delay(80);
  assert.equal(fixture.count("/api/v1/auth/password-login"), loginBefore + 1, "duplicate_login_post");
  fixture.holdLogin = false; await fixture.release("login"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "password_after_google_failure");
  results.push({ check: "Google failure does not block password and duplicate submit makes one POST", passed: true });

  fixture.email = null; fixture.google = "ready"; await navigate("/register");
  await check("registration asks only for email before ownership proof", "Boolean(document.querySelector('#auth-email'))&&!document.querySelector('#auth-password')");
  await fill("#auth-email", "new-reader@example.test"); fixture.nextError = { path: "/api/v1/auth/registrations", status: 403 };
  const registrations = fixture.count("/api/v1/auth/registrations"); const challenges = fixture.sequence;
  await click("[data-testid=password-auth-submit]"); await waitFor("Boolean(document.querySelector('[data-testid=password-auth-error]'))", "registration_challenge_error");
  await delay(100); assert.equal(fixture.count("/api/v1/auth/registrations"), registrations + 1);
  await click("[data-testid=password-auth-submit]"); await waitFor("location.pathname==='/registration-sent'", "registration_ack");
  assert.equal(fixture.sequence, challenges + 2); assert.deepEqual(Object.keys(fixture.calls.findLast((call) => call.path === "/api/v1/auth/registrations").body), ["email"]);
  results.push({ check: "403 requires manual email-only resubmit with a fresh challenge", passed: true });
  await check("registration response stays generic", "document.body.textContent.includes('If this address is eligible')&&!document.body.textContent.includes('private-server')");

  await navigate("/forgot-password"); await waitFor("!document.querySelector('#auth-email').disabled", "reset_request_ready"); await fill("#auth-email", EMAIL_A);
  fixture.nextError = { path: "/api/v1/auth/password-reset-requests", status: 429 };
  const recoveryBefore = fixture.count("/api/v1/auth/password-reset-requests"); await click("[data-testid=password-auth-submit]");
  await waitFor("document.body.textContent.includes('Too many attempts')", "recovery_throttled");
  await check("throttling disables premature retry and hides diagnostic", "document.querySelector('[data-testid=password-auth-submit]').disabled&&!document.body.textContent.includes('private-server')");
  await waitFor("!document.querySelector('[data-testid=password-auth-submit]').disabled", "retry_after_elapsed", 3000);
  assert.equal(fixture.count("/api/v1/auth/password-reset-requests"), recoveryBefore + 1, "no_automatic_recovery_retry");
  await click("[data-testid=password-auth-submit]"); await waitFor("location.pathname==='/check-email'", "recovery_generic_ack");
  results.push({ check: "Retry-After is honored without automatic email replay", passed: true });

  await navigate(`/verify-email#token=${VERIFY_PROOF}`); await noBearerLeak("verification proof is removed from URL DOM cookies and storage");
  await proofSubmission(); await waitFor("document.querySelector('h1')?.textContent==='Your account is ready'", "verification_complete");
  await check("verification completion does not auto-login or show an invalid-link CTA", "!document.querySelector('.opal-workspace')&&!document.querySelector('#auth-password')&&!document.querySelector('a[href=\"/register\"]')");
  // A second email link can update the fragment in the already-open document.
  await evaluate(`location.hash=${escaped(`token=${VERIFY_PROOF}`)}`);
  await proofSubmission(); await noBearerLeak("same-document verification link is consumed without persistence");
  await waitFor("document.querySelector('h1')?.textContent==='Request a new link'", "used_verification_rejected");
  results.push({ check: "used verification proof receives recovery state", passed: true });
  const resetCount = fixture.count("/api/v1/auth/password-resets"); await navigate("/reset-password");
  await check("missing reset proof has no password submission", "document.querySelector('h1').textContent==='Request a new link'&&!document.querySelector('[data-testid=password-auth-form]')");
  assert.equal(fixture.count("/api/v1/auth/password-resets"), resetCount);
  fixture.email = EMAIL_A;
  await navigate(`/reset-password#token=${RESET_PROOF}`); await noBearerLeak("reset proof is removed from URL DOM cookies and storage");
  await proofSubmission(); await waitFor("document.querySelector('h1')?.textContent==='Password updated'", "reset_complete");
  await check("reset completion returns to sign-in without auto-login", "!document.querySelector('.opal-workspace')&&Boolean(document.querySelector('a[href=\"/signin\"]'))");
  await navigate(`/reset-password#token=${VERIFY_PROOF}`); await proofSubmission(); await waitFor("document.querySelector('h1')?.textContent==='Request a new link'", "wrong_purpose_rejected");
  results.push({ check: "wrong-purpose proof fails with safe recovery state", passed: true });

  await navigate("/signin?return=https%3A%2F%2Fattacker.invalid%2Fcollect#untrusted");
  await check("untrusted return destinations and fragments are discarded", "location.pathname==='/signin'&&location.search===''&&location.hash===''");
  await evaluate("localStorage.setItem('VITE_AQUA_UI_SHELL','attacker-choice');localStorage.setItem('aqua-ui-shell','attacker-choice');localStorage.setItem('VITE_AQUA_DEMO_MODE','true')");
  await navigate("/signin?VITE_AQUA_UI_SHELL=attacker-choice&shell=attacker-choice&demo=true#legacy");
  await check("URL and storage cannot select a shell or bypass real sign-in", "location.search===''&&location.hash===''&&!document.querySelector('.opal-workspace')&&Boolean(document.querySelector('#auth-password'))");
  await waitFor("Boolean(document.querySelector('[data-testid=fixture-google-button]'))", "google_button_ready");
  await click("[data-testid=fixture-google-button]"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "google_workspace");
  await assertShell(check);
  await evaluate("localStorage.removeItem('VITE_AQUA_UI_SHELL');localStorage.removeItem('aqua-ui-shell');localStorage.removeItem('VITE_AQUA_DEMO_MODE')");
  results.push({ check: "supported Google callback reaches canonical workspace", passed: true });
  fixture.queryMessage = "<img src='https://attacker.invalid/collect' onerror='window.__fixtureScriptExecuted=1'>\n\n[unsafe](javascript:window.__fixtureScriptExecuted=1)\n\nSynthetic safe answer.";
  await fill(".opal-composer textarea", "Synthetic hostile-output request"); await click("[aria-label='Send message']");
  await waitFor("document.querySelector('.conversation')?.textContent.includes('Synthetic safe answer')", "hostile_answer_rendered");
  await check("hostile output cannot execute or create external active elements", "window.__fixtureScriptExecuted===0&&![...document.querySelectorAll('.conversation a,.conversation img,.conversation iframe')].some(el=>/attacker|javascript:/.test(el.getAttribute('href')||el.getAttribute('src')||''))");

  // Two real pages share the ephemeral browser profile and fixture session.
  // BroadcastChannel, React lifecycles and stale-response fencing remain real.
  const primarySession = sessionId;
  const secondary = await cdp.send("Target.createTarget", { url: "about:blank" }, null);
  ({ sessionId } = await cdp.send("Target.attachToTarget", { targetId: secondary.targetId, flatten: true }, null));
  const secondarySession = sessionId;
  await preparePage(); await viewport(1440, 980); await navigate("/");
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "second_tab_workspace");
  await fill(".opal-composer textarea", "Private account A second-tab draft");
  sessionId = primarySession; await menu("Sign out");
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('.opal-workspace')", "primary_logout_complete");
  sessionId = secondarySession;
  await waitFor("Boolean(document.querySelector('#auth-email'))&&!document.querySelector('.opal-workspace')", "other_tab_logout_lock");
  await check("confirmed logout clears private state in the other real tab", "!document.body.textContent.includes('Private account A second-tab draft')");
  await signIn(EMAIL_B);
  sessionId = primarySession;
  await waitFor(`Boolean(document.querySelector('.opal-workspace:not([hidden])'))&&document.body.textContent.includes('Fixture Reader B')`, "other_tab_account_switch");
  await check("other-tab account switch never reuses old account conversation", "document.querySelector('.opal-composer textarea').value===''&&!document.body.textContent.includes('Synthetic safe answer')&&!document.body.textContent.includes('Private account A second-tab draft')");
  await fill(".opal-composer textarea", "Account B draft before ambiguous reset");
  sessionId = secondarySession;
  await navigate(`/reset-password#token=${RESET_PROOF}`);
  fixture.holdReset = true;
  fixture.nextError = { path: "/api/v1/auth/password-resets", status: 503, sessionsRevoked: true };
  const ambiguousBefore = fixture.count("/api/v1/auth/password-resets");
  await proofSubmission();
  sessionId = primarySession;
  await waitFor("!document.querySelector('.opal-workspace')&&Boolean(document.querySelector('#auth-email'))", "other_tab_reset_initial_lock");
  // Advance only this browser clock past the foreground refresh bound. The
  // fixture still holds the reset before commit, so its old session is valid.
  await evaluate("window.__fixtureRealNow=Date.now;Date.now=()=>window.__fixtureRealNow()+11000");
  await cdp.send("Page.bringToFront");
  await evaluate("window.dispatchEvent(new Event('focus'))");
  await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "old_session_revalidated_while_reset_held");
  assert.equal(fixture.email, EMAIL_B, "held_reset_has_not_committed");
  await fill(".opal-composer textarea", "Account B revalidated while reset pending");
  results.push({ check: "held reset permits reproducing old-session foreground revalidation", passed: true });
  fixture.holdReset = false; await fixture.release("reset");
  sessionId = secondarySession;
  await waitFor("Boolean(document.querySelector('[data-testid=password-auth-error]'))", "ambiguous_reset_error");
  await check("ambiguous reset response keeps this tab out of its workspace", "!document.querySelector('.opal-workspace:not([hidden])')&&!document.body.textContent.includes('private-server')");
  sessionId = primarySession;
  await waitFor("!document.querySelector('.opal-workspace')&&Boolean(document.querySelector('#auth-email'))", "other_tab_reset_locked");
  await check("reset attempt clears other-tab private draft even on ambiguous response", "!document.body.textContent.includes('Account B draft before ambiguous reset')&&!document.body.textContent.includes('Account B revalidated while reset pending')");
  await evaluate("Date.now=window.__fixtureRealNow;delete window.__fixtureRealNow");
  await check("cross-tab notifications carry only bounded event metadata", "window.__fixtureSessionEvents.length>0&&window.__fixtureSessionEvents.every(value=>value&&Object.keys(value).length===1&&['changed','locked'].includes(value.type))");
  await delay(100); assert.equal(fixture.count("/api/v1/auth/password-resets"), ambiguousBefore + 1, "ambiguous_reset_never_auto_replays");
  results.push({ check: "ambiguous reset has exactly one explicit POST across both tabs", passed: true });
  closingSessions.add(secondarySession);
  await cdp.send("Target.closeTarget", { targetId: secondary.targetId }, null); sessions.delete(secondarySession);
  await signIn(EMAIL_A);

  for (const [width, height] of [[1024, 768], [768, 1024]]) {
    await viewport(width, height); await navigate("/");
    await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "intermediate_home");
    await assertEssentialControls(check, `${width} pixel intermediate workspace keeps composer and account actions reachable`);
    await screenshot(`home-intermediate-${width}x${height}`);
  }

  await viewport(390, 844, true); await navigate("/"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "mobile_home");
  await assertSafeAreaStyles(check);
  performanceSamples.push(await capturePerformance(evaluate, "mobile-workspace"));
  await screenshot("home-mobile-390x844");
  // Keyboard activation preserves the native dialog's real return-focus owner.
  // HTMLElement.click() alone does not focus a button like actual interaction.
  await evaluate("document.querySelector('[aria-label=\"Open navigation\"]').focus()"); await click("[aria-label='Open navigation']");
  await waitFor("Boolean(document.querySelector('dialog[open]'))", "mobile_drawer");
  await key("Tab"); await check("mobile drawer contains keyboard focus", "document.querySelector('dialog[open]').contains(document.activeElement)");
  await key("Escape"); await waitFor("!document.querySelector('dialog[open]')&&document.activeElement.getAttribute('aria-label')==='Open navigation'", "drawer_closed_focus_returned");
  await check("mobile drawer Escape returns focus", "!document.querySelector('dialog[open]')&&document.activeElement.getAttribute('aria-label')==='Open navigation'");
  await viewport(390, 420, true); await fill(".opal-composer textarea", "Draft with a small mobile viewport");
  await assertEssentialControls(check, "small mobile viewport keeps typed composer and send action unobscured");
  await screenshot("home-mobile-keyboard-height-390x420");
  await viewport(390, 844, true); await enlargeText(evaluate);
  await evaluate("document.querySelector('.opal-composer').scrollIntoView({block:'center'})");
  await assertEssentialControls(check, "200 percent workspace text keeps composer and account menu visible and operable");
  await click(".workspace-header [aria-label='Account menu']"); await clickText("Settings", "[role=menuitem]");
  await waitFor("Boolean(document.querySelector('#settings-heading'))", "enlarged_settings_reachable");
  await clickText("Back to workspace");
  await check("200 percent workspace text preserves draft across reachable Settings", "document.querySelector('.opal-composer textarea').value==='Draft with a small mobile viewport'");
  await screenshot("home-mobile-text-200-percent");
  await navigate("/"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "workspace_text_reset");
  fixture.queryMessage = Array.from({ length: 12 }, (_, index) => `Synthetic enlarged-text answer paragraph ${index + 1}. This is fixture content only.`).join("\n\n");
  await fill(".opal-composer textarea", "Synthetic enlarged-text active conversation"); await click("[aria-label='Send message']");
  await waitFor("document.querySelector('.conversation')?.textContent.includes('Synthetic enlarged-text answer paragraph 12')", "enlarged_active_answer");
  await fill(".opal-composer textarea", "Draft in an enlarged active conversation"); await enlargeText(evaluate);
  await evaluate("document.querySelector('.opal-composer').scrollIntoView({block:'center'})");
  await assertEssentialControls(check, "200 percent active conversation keeps draft composer and send action reachable");
  await screenshot("active-mobile-text-200-percent");
  await navigate("/"); await waitFor("Boolean(document.querySelector('.opal-workspace:not([hidden])'))", "active_text_reset");
  await viewport(320, 844, true); await screenshot("home-mobile-320-reflow");
  await check("320 CSS pixel home has no page overflow", "document.documentElement.scrollWidth<=innerWidth+1");
  await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }, { name: "forced-colors", value: "active" }] });
  await screenshot("home-forced-colors-reduced-motion");
  await check("forced colors and reduced motion preserve essential controls", "matchMedia('(forced-colors: active)').matches&&matchMedia('(prefers-reduced-motion: reduce)').matches&&Boolean(document.querySelector('[aria-label=\"Send message\"]'))");
  for (const scheme of ["light", "dark"]) {
    await cdp.send("Emulation.setEmulatedMedia", { features: [{ name: "forced-colors", value: "active" }, { name: "prefers-color-scheme", value: scheme }, { name: "prefers-reduced-motion", value: "reduce" }] });
    await fill(".opal-composer textarea", "Synthetic high-contrast draft");
    await check(`forced colors ${scheme} uses a visible arrow mask`, "(()=>{const icon=document.querySelector('.opal-send__contrast-icon'),button=icon.closest('button');const style=getComputedStyle(icon);return !button.disabled&&style.display!=='none'&&style.maskImage!=='none'&&style.backgroundColor!==getComputedStyle(button).backgroundColor})()");
    await check(`forced colors ${scheme} keeps header action glyphs visible`, "['New chat','Account menu'].every(label=>{const button=document.querySelector('.workspace-header [aria-label=\"'+label+'\"]');const icon=button?.querySelector('.icon-contrast');if(!icon)return false;const style=getComputedStyle(icon);return style.display!=='none'&&style.maskImage!=='none'&&style.backgroundColor!==getComputedStyle(button).backgroundColor})");
    await screenshot(`home-forced-colors-${scheme}-enabled`);
    await fill(".opal-composer textarea", "");
    await check(`forced colors ${scheme} preserves disabled arrow contrast`, "(()=>{const icon=document.querySelector('.opal-send__contrast-icon'),button=icon.closest('button');return button.disabled&&getComputedStyle(icon).maskImage!=='none'&&getComputedStyle(icon).backgroundColor!==getComputedStyle(button).backgroundColor})()");
  }
  await cdp.send("Emulation.setEmulatedMedia", { features: [] });
  fixture.email = null; await viewport(390, 844, true); await navigate("/signin"); await screenshot("signin-mobile-390x844");
  await assertLoginDelivery(check); performanceSamples.push(await capturePerformance(evaluate, "mobile-signin"));
  await viewport(320, 844, true); await check("320 CSS pixel sign-in has no page overflow", "document.documentElement.scrollWidth<=innerWidth+1");
  await screenshot("signin-mobile-320-reflow");
  await evaluate("(()=>{const nodes=[...document.querySelectorAll('h1,h2,p,label,button,input,a,small')].map(el=>({el,size:parseFloat(getComputedStyle(el).fontSize),line:parseFloat(getComputedStyle(el).lineHeight)}));for(const {el,size,line} of nodes){el.style.fontSize=`${size*2}px`;if(Number.isFinite(line))el.style.lineHeight=`${line*2}px`;}return true})()");
  await check("200 percent text preserves page reflow", "document.documentElement.scrollWidth<=innerWidth+1");
  await evaluate("document.querySelector('[data-testid=password-auth-submit]').scrollIntoView({block:'center'})");
  await check("200 percent text keeps sign-in reachable", "(()=>{const r=document.querySelector('[data-testid=password-auth-submit]').getBoundingClientRect();return r.width>0&&r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1})()");
  await screenshot("signin-mobile-text-200-percent");
  await navigate("/unknown-fixture-route"); await check("unknown route has recovery navigation", "document.querySelector('h1').textContent==='Page not found'&&Boolean(document.querySelector('.not-found button'))");
  await navigate("/privacy"); await check("public policy remains readable signed out", "Boolean(document.querySelector('[data-testid=legal-page]'))&&!document.querySelector('.auth-page')");

  assert.equal(fixture.forbiddenCalls, 0, "unexpected_fixture_api_call"); assert.equal(consoleLeaks, 0, "sensitive_console_value");
  assert.equal(runtimeErrors, 0, "uncaught_browser_error"); assert.equal(protocolFailures.length, 0, "interception_failure");
  assert.equal(external.length, 0, "unexpected_external_request_attempt"); assert.ok(apiRequests <= MAX_API && requestCount <= MAX_REQUESTS);
  results.push({ check: "all traffic bounded and intercepted; no external calls or console bearer leak", passed: true });
  await writeFile(path.join(artifacts, "browser-version.json"), JSON.stringify({ browser: version.product }, null, 2) + "\n");
  await writeFile(path.join(artifacts, "font-diagnostics.json"), JSON.stringify(fonts, null, 2) + "\n");
} catch (error) {
  failure = error instanceof assert.AssertionError ? error.message.split("\n")[0] : String(error.message || "browser_gate_failed");
  if (sessionId) failureLayout = await captureControlBounds(evaluate).catch(() => null);
  if (sessionId) await screenshot("failure-current-view").catch(() => {});
} finally {
  clearTimeout(deadline);
  if (browser) {
    if (browser.exitCode === null) { await cdp?.send("Browser.close", {}, null).catch(() => {}); await Promise.race([closed, delay(1500)]); }
    if (browser.exitCode === null) { browser.kill(); await Promise.race([closed, delay(1000)]); }
  }
  cdp?.fail(); server?.closeAllConnections(); if (server?.listening) await new Promise((resolve) => server.close(resolve));
  if (profile) {
    const resolved = await realpath(profile); assert.equal(path.dirname(resolved), temporaryRoot);
    assert.ok(path.basename(resolved).startsWith("aqua-p05-browser-")); assert.equal((await lstat(profile)).isSymbolicLink(), false);
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
  cleanup = !browser || browser.exitCode !== null;
}
const report = { status: failure ? "failed" : "passed", failure, failureLayout, checked_utc: new Date().toISOString(),
  mode: "production_build_synthetic_api_browser", expected_shell: EXPECTED_SHELL, loadedAssets, results, screenshots, performanceSamples,
  limits: { maximum_seconds: MAX_MS / 1000, maximum_requests: MAX_REQUESTS, maximum_api_requests: MAX_API },
  observations: { requestCount, staticRequests, apiRequests, external_attempts: external.length, consoleLeaks, runtimeErrors, forbidden_api_calls: fixture.forbiddenCalls, protocolFailures, canceledInterceptions, scrollObservations },
  cleanup: cleanup ? "browser_stopped_loopback_closed_temporary_profile_removed" : "failed",
  elapsed_seconds: Math.round((performance.now() - started) / 10) / 100,
  limitations: ["Synthetic intercepted API and GIS contracts; no actual backend, Google, email, database or production-origin validation.", "400% reflow represented by a 320 CSS-pixel viewport; 200% text doubles computed text sizes.", "Small viewport models keyboard-constrained space; it is not an actual mobile OS keyboard test.", "Navigation timings are local observations, not production performance guarantees; initial delivery byte limits are deterministic.", "Keyboard and semantic assertions are not a complete screen-reader or contrast audit.", "Screenshots require human/agent visual review; saving them alone is not visual approval."] };
await ensureArtifacts(); await writeFile(path.join(artifacts, "report.json"), JSON.stringify(report, null, 2) + "\n");
console.log(JSON.stringify({ status: report.status, checks: results.length, failure, report: path.join(artifacts, "report.json"), cleanup: report.cleanup }));
if (failure || !cleanup) process.exitCode = 1;
