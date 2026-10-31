// Real built assets + isolated private API bridge. Never serve a public origin.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFile, readdir, lstat, realpath, mkdtemp, mkdir, writeFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import { createHash } from "node:crypto";
import { FixtureBridge } from "./p05-browser-bridge.mjs";
import { BrowserPipe } from "./p05-browser-pipe.mjs";
import { browserFixtureMode, SECURE_ACCOUNT_ORIGIN, staticFixtureResponse } from "./p10b-browser-mode.mjs";

export const LIMITS = Object.freeze({ milliseconds: 150000, requests: 250, api: 160, paused: 16, perSecond: 5, bodyBytes: 16384, fakeJobs: 12 });
const delay = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const quote = JSON.stringify;
const visible = "el=>el.getClientRects().length&&!el.closest('[hidden],[inert]')";
function configured(name) {
  const value = process.env[name];
  if (!value || !path.isAbsolute(value) || value.length > 4096 || value.includes("\0")) throw Error("fixture_configuration_invalid");
  return path.resolve(value);
}

export function setupDiagnostic(error, ctx) {
  const token = (value, pattern = /^[a-zA-Z0-9_]{1,96}$/) => typeof value === 'string' && value.length <= 96 && pattern.test(value) ? value : null;
  const diagnostic = ctx?.cdp?.diagnostic;
  const bridge = ctx?.bridge?.diagnostic;
  return { category: token(error?.message, /^[a-z0-9_]{1,96}$/) || token(error?.name) || 'setup_failed', stage: token(ctx?.stage) || 'configuration',
    browser: diagnostic ? { reason: token(diagnostic.reason), stage: token(diagnostic.stage), method: token(diagnostic.method, /^[A-Za-z]+\.[A-Za-z]+$/), pending_count: Number.isSafeInteger(diagnostic.pending_count) ? diagnostic.pending_count : null } : null,
    bridge: bridge ? { kind: token(bridge.kind), category: token(bridge.category), stage: token(bridge.stage), module: token(bridge.module, /^[a-zA-Z0-9_.]{1,96}$/) } : null,
    cleanup: ctx?.cleanup ? { browser_stopped: ctx.cleanup.browser_stopped === true, profile_removed: ctx.cleanup.profile_removed === true, loopback_closed: ctx.cleanup.loopback_closed === true, backend_resources_removed: ctx.cleanup.backend_resources_removed === true,
      backend_status: token(ctx.cleanup.backend?.status), backend_cleanup: token(ctx.cleanup.backend?.cleanup), remaining_resources: Array.isArray(ctx.cleanup.backend?.remaining_ids) ? ctx.cleanup.backend.remaining_ids.length : null } : null };
}

export async function openP08Browser(options) {
  const { secureAccountFixture } = browserFixtureMode(options);
  const ctx = { started: performance.now(), stage: "configuration", results: [], screenshots: [], assets: [], external: 0, requests: 0, api: 0,
    errors: [], protocolDiagnostics: [], runtimeErrors: 0, consoleLeaks: 0, navigating: false, pending: 0, maximumPending: 0, secrets: new Set() };
  const artifacts = configured("AQUA_P08_ARTIFACT_DIR"), dist = configured("AQUA_P08_DIST"), executable = configured("AQUA_P08_BRIDGE_EXECUTABLE");
  const argv = JSON.parse(process.env.AQUA_P08_BRIDGE_ARGS_JSON || "[]");
  if (!Array.isArray(argv) || !argv.length || argv.length > 12 || argv.some((arg) => typeof arg !== "string" || arg.length > 1024)) throw Error("fixture_arguments_invalid");
  const imageIndex = argv.indexOf("--image");
  if (imageIndex < 0 || argv.lastIndexOf("--image") !== imageIndex || !/^sha256:[a-f0-9]{64}$/.test(argv[imageIndex + 1] || "")) throw Error("immutable_fixture_image_required");
  if (secureAccountFixture && !argv.some(arg => ["/tools/checks/p10b_browser_backend.py","/tools/checks/p10c_browser_backend.py"].some(entry=>arg.endsWith(entry)))) throw Error("secure_account_fixture_entry_required");
  ctx.backendImage = argv[imageIndex + 1];
  await mkdir(artifacts, { recursive: true }); if ((await lstat(artifacts)).isSymbolicLink()) throw Error("artifact_symlink_denied");
  ctx.artifacts = artifacts;
  ctx.evaluate = async (expression) => {
    const value = await ctx.cdp.send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
    if (value.exceptionDetails) throw Error("page_evaluation_failed"); return value.result.value;
  };
  ctx.waitFor = async (expression, label, milliseconds = 12000) => {
    ctx.stage = label; const until = performance.now() + milliseconds;
    while (performance.now() < until) { if (await ctx.evaluate(expression)) return; await delay(40); }
    throw Error("browser_condition_failed");
  };
  ctx.check = async (label, expression) => { ctx.stage = label; if (await ctx.evaluate(expression) !== true) throw Error("browser_assertion_failed"); ctx.results.push({ check: label, passed: true }); };
  ctx.click = async (selector) => { await ctx.waitFor(`(()=>{const el=[...document.querySelectorAll(${quote(selector)})].find(${visible});return Boolean(el&&!el.disabled)})()`, "click_control_ready");
    await ctx.evaluate(`(()=>{const el=[...document.querySelectorAll(${quote(selector)})].find(${visible});el.focus();el.click();return true})()`); };
  ctx.clickText = async (text, selector = "button,a") => {
    ctx.stage = "click_" + text.slice(0, 64).replace(/[^a-zA-Z0-9 ]/g, "_");
    await ctx.evaluate(`(()=>{const el=[...document.querySelectorAll(${quote(selector)})].find(el=>(${visible})(el)&&el.textContent.trim()===${quote(text)});if(!el||el.disabled)throw Error();el.focus();el.click();return true})()`);
  };
  ctx.fill = async (selector, value) => { await ctx.waitFor(`Boolean(document.querySelector(${quote(selector)}))&&!document.querySelector(${quote(selector)}).disabled`, "editable_field_ready");
    await ctx.evaluate(`(()=>{const el=document.querySelector(${quote(selector)});el.focus();const p=el instanceof HTMLTextAreaElement?HTMLTextAreaElement.prototype:HTMLInputElement.prototype;Object.getOwnPropertyDescriptor(p,'value').set.call(el,${quote(value)});el.dispatchEvent(new Event('input',{bubbles:true}));el.dispatchEvent(new Event('change',{bubbles:true}));return true})()`); };
  ctx.navigate = async (route) => { ctx.navigating = true; try { await ctx.cdp.send("Page.navigate", { url: "about:blank" }); await ctx.waitFor("location.href==='about:blank'", "navigation_reset");
    await ctx.cdp.send("Page.navigate", { url: ctx.origin + route }); await ctx.waitFor("document.readyState==='complete'&&Boolean(document.querySelector('.auth-page,.opal-workspace'))", "application_ready"); } finally { ctx.navigating = false; } };
  ctx.rawRequest = (method, route, body, csrf) => ctx.evaluate(`(async()=>{const r=await fetch(${quote(route)},{method:${quote(method)},credentials:'same-origin',cache:'no-store',redirect:'error',headers:${quote({ ...(body ? { "Content-Type": "application/json" } : {}), ...(csrf ? { "X-CSRF-Token": csrf } : {}) })},${body ? `body:${quote(JSON.stringify(body))},` : ""}});const t=await r.text();if(t.length>16384)throw Error();return {status:r.status,body:t}})()`);
  ctx.screenshot = async (name) => { const { data } = await ctx.cdp.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: false });
    if (!/^[a-z0-9-]{1,80}$/.test(name) || data.length > 8 * 1024 * 1024) throw Error("screenshot_bound");
    await writeFile(path.join(artifacts, name + ".png"), Buffer.from(data, "base64")); ctx.screenshots.push(name + ".png"); };
  ctx.close = async () => {
    clearTimeout(ctx.deadline);
    // Finish already-forwarded fixture responses before Browser.close. A close
    // racing Fetch.fulfillRequest is a protocol failure, not clean shutdown.
    const drainBy = performance.now() + 5000;
    while (ctx.pending > 0 && performance.now() < drainBy && !ctx.cdp?.failure) await delay(25);
    if (ctx.pending > 0 && ctx.errors.length < 16) ctx.errors.push("interception_drain_unconfirmed");
    if (ctx.cdp) await ctx.cdp.stop();
    let finished = ctx.bridge?.finished;
    if (ctx.bridge && !finished && ctx.bridge.process.exitCode === null) { try { finished = await ctx.bridge.send("finish", {}, 30000); } catch { finished = ctx.bridge.finished; } }
    if (ctx.bridge) { ctx.bridge.process.stdin.end(); await Promise.race([ctx.bridge.closed, delay(3000)]); if (ctx.bridge.process.exitCode === null) ctx.bridge.process.kill(); finished ||= ctx.bridge.finished; }
    ctx.server?.closeAllConnections(); if (ctx.server?.listening) await new Promise((resolve) => ctx.server.close(resolve));
    let profileRemoved = false;
    if (ctx.profile) { const temporary = await realpath(tmpdir()), target = await realpath(ctx.profile);
      if (path.dirname(target) !== temporary || !path.basename(target).startsWith("aqua-p08-browser-") || (await lstat(ctx.profile)).isSymbolicLink()) throw Error("profile_cleanup_scope_invalid");
      await rm(ctx.profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 }); profileRemoved = true; }
    ctx.cleanup = { browser_stopped: ctx.cdp?.stopped === true && !ctx.cdp?.cleanupFailure, profile_removed: profileRemoved, loopback_closed: !ctx.server?.listening,
      backend_resources_removed: finished?.status === "passed" && finished.report?.cleanup === "removed_and_absence_confirmed" && finished.report?.remaining_ids?.length === 0,
      backend: finished?.report || null };
  };
  try {
    const files = new Map(); let total = 0;
    async function preload(directory, prefix = "") { for (const item of await readdir(directory, { withFileTypes: true })) { const full = path.join(directory, item.name), key = prefix + "/" + item.name;
      const stat=await lstat(full),inside=path.relative(scope,await realpath(full));
      if (stat.isSymbolicLink()||!inside||inside.startsWith('..')||path.isAbsolute(inside)) throw Error("dist_symlink_denied");
      if (stat.isDirectory()) await preload(full, key); else if (stat.isFile()) { const data = await readFile(full); total += data.length;
        if (data.length > 8 * 1024 * 1024 || total > 32 * 1024 * 1024 || files.size >= 300) throw Error("dist_bound"); files.set(key, data); }else throw Error("dist_regular_file_required"); } }
    if ((await lstat(dist)).isSymbolicLink() || !(await lstat(dist)).isDirectory()) throw Error("dist_invalid");
    const scope=await realpath(dist);
    await preload(dist); if (!files.has("/index.html")) throw Error("production_build_required");
    ctx.assets = [...files].map(([name, data]) => ({ name, bytes: data.length, sha256: createHash("sha256").update(data).digest("hex") }));
    if (secureAccountFixture) {
      ctx.origin = SECURE_ACCOUNT_ORIGIN;
      ctx.secureAccountFixture = { mode: "cdp_fulfilled_reserved_https_origin", dns_socket_tls_transport_tested: false };
    } else {
    ctx.server = createServer((request, response) => { if (request.method !== "GET") { response.writeHead(405); response.end(); return; }
      const pathname = new URL(request.url, "http://127.0.0.1").pathname, key = files.has(pathname) ? pathname : !path.extname(pathname) ? "/index.html" : null;
      if (!key) { response.writeHead(pathname === "/favicon.ico" ? 204 : 404); response.end(); return; }
      const type = { ".html": "text/html", ".js": "text/javascript", ".css": "text/css", ".woff2": "font/woff2", ".svg": "image/svg+xml" }[path.extname(key)] || "application/octet-stream";
      response.writeHead(200, { "Content-Type": type, "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer" }); response.end(files.get(key)); });
    await new Promise((resolve) => ctx.server.listen(0, "127.0.0.1", resolve)); ctx.origin = `http://127.0.0.1:${ctx.server.address().port}`;
    }
    ctx.bridge = new FixtureBridge(executable, argv, ctx.origin); const ready = await ctx.bridge.ready;
    if (ready.origin !== ctx.origin || ready.schema_version !== 7 || ready.dataset_grants !== 0 || ready.network !== "none" || ready.workspace_analysis_fixture !== true) throw Error("fixture_boundary_invalid");
    ctx.accountIdentityFixture=ready.account_identity_fixture===true;
    if (secureAccountFixture && ready.account_security_fixture !== true) throw Error("secure_account_fixture_required");
    if ((await ctx.bridge.send("workspace_stats")).p08_presentation_fixture !== true) throw Error("p08_fixture_required");
    ctx.profile = await mkdtemp(path.join(await realpath(tmpdir()), "aqua-p08-browser-"));
    const chrome = process.env.AQUA_CHROME_EXECUTABLE || (process.platform === "win32" ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" : "/usr/bin/google-chrome");
    const env = Object.fromEntries(["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "APPDATA", "HOME"].filter((name) => process.env[name]).map((name) => [name, process.env[name]]));
    ctx.browser = spawn(chrome, ["--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking", "--disable-component-update", "--disable-sync", "--disable-extensions", "--disable-default-apps", "--no-pings", "--metrics-recording-only", "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1", "--remote-debugging-pipe", `--user-data-dir=${ctx.profile}`, "about:blank"],
      { windowsHide: true, stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"], env });
    ctx.cdp = new BrowserPipe(ctx.browser, { session: () => ctx.sessionId, deadline: ctx.started + LIMITS.milliseconds });
    ctx.deadline = setTimeout(() => ctx.cdp.fail("browser_suite_deadline"), Math.max(1, LIMITS.milliseconds - (performance.now() - ctx.started)));
    ctx.browserVersion = (await ctx.cdp.ready()).product;
    const targets = await ctx.cdp.send("Target.getTargets"); ({ sessionId: ctx.sessionId } = await ctx.cdp.send("Target.attachToTarget", { targetId: targets.targetInfos.find((item) => item.type === "page").targetId, flatten: true }));
    let queue = Promise.resolve(), nextRequest = 0; const aborted = new Set();
    if (secureAccountFixture) ctx.probeCopiedSession = token => {
      if (typeof token !== "string" || !/^v2\.[A-Za-z0-9_-]{43}$/.test(token)) throw Error("copied_session_probe_invalid");
      if (++ctx.requests > LIMITS.requests || ++ctx.api > LIMITS.api || performance.now() - ctx.started > LIMITS.milliseconds) throw Error("api_budget");
      ctx.secrets.add(token);
      const probe = queue.then(async () => {
        await delay(Math.max(0, nextRequest - performance.now())); nextRequest = performance.now() + 1000 / LIMITS.perSecond;
        const result = await ctx.bridge.send("request", { method: "GET", path: "/api/auth/me", headers: [["Cookie", "__Host-aqua_session=" + token]], bodyBase64: "" });
        if (!Number.isInteger(result.status) || !Array.isArray(result.headers) || Buffer.from(result.bodyBase64 || "", "base64").length > LIMITS.bodyBytes) throw Error("bridge_response_invalid");
        return result.status;
      });
      queue = probe.then(() => undefined, () => undefined);
      return probe;
    };
    ctx.cdp.onEvent = (event) => {
      if (event.sessionId !== ctx.sessionId) return;
      if (ctx.cdp.stopping) return;
      if (event.method === "Runtime.exceptionThrown") ctx.runtimeErrors++;
      if (event.method === "Runtime.consoleAPICalled" && [...ctx.secrets].some((secret) => JSON.stringify(event.params.args).includes(secret))) ctx.consoleLeaks++;
      if (event.method === "Network.loadingFailed" && event.params.canceled && aborted.size < LIMITS.requests) aborted.add(event.params.requestId);
      if (event.method !== "Fetch.requestPaused") return;
      if (++ctx.requests > LIMITS.requests || ++ctx.pending > LIMITS.paused || performance.now() - ctx.started > LIMITS.milliseconds) { ctx.cdp.fail("browser_suite_deadline"); return; }
      ctx.maximumPending = Math.max(ctx.maximumPending, ctx.pending); const navigating = ctx.navigating;
      queue = queue.then(async () => { const { requestId, request } = event.params, url = new URL(request.url); await delay(Math.max(0, nextRequest - performance.now())); nextRequest = performance.now() + 1000 / LIMITS.perSecond;
        if (url.origin === ctx.origin && url.pathname.startsWith("/api/")) {
          if (++ctx.api > LIMITS.api || Buffer.byteLength(request.postData || "") > LIMITS.bodyBytes) throw Error("api_budget");
          const result = await ctx.bridge.send("request", { method: request.method, path: url.pathname + url.search, headers: Object.entries(request.headers), bodyBase64: Buffer.from(request.postData || "").toString("base64") });
          if (!Number.isInteger(result.status) || !Array.isArray(result.headers) || Buffer.from(result.bodyBase64 || "", "base64").length > LIMITS.bodyBytes) throw Error("bridge_response_invalid");
          const remember = value => { if (typeof value === "string" && value.length >= 20 && value.length <= 1024 && ctx.secrets.size < 512) ctx.secrets.add(value); };
          try { const value = JSON.parse(Buffer.from(result.bodyBase64 || "", "base64").toString("utf8")); remember(value.csrf_token); remember(value.nonce); remember(value.challenge_token); remember(value.proof_token);remember(value.request_token);remember(value.candidate_token); } catch { /* Empty/non-JSON responses carry no structured proof. */ }
          for (const [name, value] of result.headers) if (name.toLowerCase() === "set-cookie") remember(value.split(";", 1)[0].split("=").slice(1).join("="));
          await ctx.cdp.send("Fetch.fulfillRequest", { requestId, responseCode: result.status, responseHeaders: result.headers.map(([name, value]) => ({ name, value })), ...(result.status === 204 ? {} : { body: result.bodyBase64 || "" }) });
        } else if (url.origin === ctx.origin && request.method === "GET") {
          if (secureAccountFixture) { const result = staticFixtureResponse(files, url); await ctx.cdp.send("Fetch.fulfillRequest", { requestId, responseCode: result.status, responseHeaders: result.headers, ...(result.status === 204 ? {} : { body: result.body }) }); }
          else await ctx.cdp.send("Fetch.continueRequest", { requestId });
        }
        else { ctx.external++; await ctx.cdp.send("Fetch.failRequest", { requestId, errorReason: "BlockedByClient" }); }
      }).catch(async (error) => { if (error.canceled) await delay(50); // Chrome may deliver its canceled marker after the closing Fetch response.
        if (!(error.canceled && (navigating || ctx.navigating || aborted.has(event.params.networkId))) && !(error.shutdownSessionMissing && ctx.cdp.stopping) && ctx.errors.length < 16) { ctx.errors.push("request_interception_failed_" + (error.protocolReason === "request_no_longer_exists" ? "cancel_unconfirmed" : "other"));
          ctx.protocolDiagnostics.push(error.browserDiagnostic || { category: ["bridge_closed", "bridge_request_timeout", "bridge_operation_failed", "bridge_exited"].includes(error.message) ? error.message : "fixed_contract_bound" }); } }).finally(() => { ctx.pending--; });
    };
    for (const method of ["Page.enable", "Network.enable", "Runtime.enable"]) await ctx.cdp.send(method);
    await ctx.cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] });
    await ctx.cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: "window.google={accounts:{id:{initialize(){},disableAutoSelect(){},renderButton(){}}}};" });
    await ctx.cdp.send("Emulation.setDeviceMetricsOverride", { width: 1440, height: 900, deviceScaleFactor: 1, mobile: false });
    return ctx;
  } catch (error) {
    try { await ctx.close(); } catch { /* Preserve the first fixed setup category. */ }
    const diagnostic = setupDiagnostic(error, ctx), failure = new Error(diagnostic.category);
    failure.setupDiagnostic = diagnostic;
    throw failure;
  }
}
