// Browser-fixture only. Diagnostics never include URLs, source text or samples.
export const CSP_BINDING = "__aquaCspViolation";
export const CSP_PROBE_PATH = "/__aqua-fixture/csp-probes.js";
const DIRECTIVES = new Set(["default-src", "script-src", "script-src-elem", "script-src-attr", "style-src", "style-src-elem", "style-src-attr", "connect-src", "img-src", "font-src", "frame-src", "worker-src", "media-src", "manifest-src", "object-src", "base-uri", "frame-ancestors", "form-action", "other"]);
const REQUIRED = ["script-src", "script-src-elem", "script-src-attr", "connect-src", "img-src", "frame-src", "object-src", "base-uri"];

function installObserver() {
  let emitted = 0, canary = false, started = false;
  const allowed = new Set(["default-src", "script-src", "script-src-elem", "script-src-attr", "style-src", "style-src-elem", "style-src-attr", "connect-src", "img-src", "font-src", "frame-src", "worker-src", "media-src", "manifest-src", "object-src", "base-uri", "frame-ancestors", "form-action"]);
  const expected = new Set(["script-src", "script-src-elem", "script-src-attr", "connect-src", "img-src", "frame-src", "object-src", "base-uri"]);
  const seen = new Set();
  Object.defineProperty(window, "__aquaCspBeginCanary", { value() {
    if (started) throw Error("csp_canary_repeated"); started = canary = true;
    return () => { canary = false; };
  } });
  addEventListener("securitypolicyviolation", event => {
    if (++emitted > 64) return;
    // Exactly one event per expected canary; additional or unrelated violations
    // still fail as application violations, even inside the short probe window.
    const deliberate = canary && expected.has(event.effectiveDirective) && !seen.has(event.effectiveDirective) && event.disposition === "enforce";
    if (deliberate) seen.add(event.effectiveDirective);
    window.__aquaCspViolation(JSON.stringify({ directive: allowed.has(event.effectiveDirective) ? event.effectiveDirective : "other",
      disposition: event.disposition === "enforce" ? "enforce" : event.disposition === "report" ? "report" : "invalid",
      phase: deliberate ? "canary" : "application" }));
  });
}
export const CSP_OBSERVER_SOURCE = `(${installObserver.toString()})();`;

function browserCanaries() {
  const finishCanary = window.__aquaCspBeginCanary();
  const parent = document.createElement("div"), originalBase = document.baseURI;
  parent.setAttribute("aria-hidden", "true"); parent.style.position = "fixed"; parent.style.left = "-10000px";
  parent.style.width = "1px"; parent.style.height = "1px"; document.body.appendChild(parent);
  const script = document.createElement("script"); script.textContent = "window.__aquaCspInlineExecuted=true"; parent.appendChild(script);
  const button = document.createElement("button"); button.setAttribute("onclick", "window.__aquaCspHandlerExecuted=true"); parent.appendChild(button); button.click();
  let evalBlocked = false;
  try { new Function("return 1")(); } catch { evalBlocked = true; }
  const base = document.createElement("base"); base.href = "https://aqua-csp-probe.invalid/base/"; document.head.appendChild(base);
  // Removing a blocked base makes Chromium re-evaluate it and emit a second
  // violation. Keep this inert probe until the fixture document is discarded.
  const baseBlocked = document.baseURI === originalBase;
  const image = document.createElement("img"); image.src = "https://aqua-csp-probe.invalid/image"; parent.appendChild(image);
  const frame = document.createElement("iframe"); frame.src = "https://aqua-csp-probe.invalid/frame"; parent.appendChild(frame);
  const object = document.createElement("object"); object.data = "https://aqua-csp-probe.invalid/object"; parent.appendChild(object);
  // The transport fixture independently blocks all external attempts if CSP fails.
  void fetch("https://aqua-csp-probe.invalid/connect", { credentials: "omit", mode: "cors", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer" }).catch(() => {});
  setTimeout(() => {
    parent.remove();
    finishCanary();
    Object.defineProperty(window, "__aquaCspProbeResult", { value: Object.freeze({ complete: true,
      inlineBlocked: window.__aquaCspInlineExecuted !== true, handlerBlocked: window.__aquaCspHandlerExecuted !== true,
      evalBlocked, baseBlocked }) });
    delete window.__aquaCspInlineExecuted; delete window.__aquaCspHandlerExecuted;
  }, 400);
}
// Loaded through a real same-origin script element; CDP never evaluates the probes.
export const CSP_PROBE_SOURCE = Buffer.from(`(${browserCanaries.toString()})();`, "utf8");

export function createCspDiagnostics(mode, sha256) {
  if (!["source", "enforced-fixture"].includes(mode) || !/^[a-f0-9]{64}$/.test(sha256)) throw Error("csp_diagnostic_invalid");
  return { mode, policy_sha256: sha256, events: 0, invalid: false, overflow: false,
    application: { enforce: {}, report: {} }, canary: { enforce: {}, report: {} }, probe_script_requests: 0, canaries_completed: false };
}

export function observeCspBinding(state, payload) {
  try {
    if (state.events >= 256) { state.overflow = true; throw Error(); }
    state.events++;
    if (typeof payload !== "string" || payload.length > 160) throw Error();
    const value = JSON.parse(payload);
    if (!value || typeof value !== "object" || Array.isArray(value) || Object.keys(value).sort().join(",") !== "directive,disposition,phase"
      || !DIRECTIVES.has(value.directive) || !["enforce", "report"].includes(value.disposition) || !["application", "canary"].includes(value.phase)
      || value.phase === "canary" && state.mode !== "enforced-fixture") throw Error();
    const bucket = state[value.phase][value.disposition];
    bucket[value.directive] = (bucket[value.directive] || 0) + 1;
  } catch { state.invalid = true; }
}

export function assertCspCoverage(state, { canaries = false } = {}) {
  if (state.invalid || state.overflow || state.events > 256
    || Object.values(state.application).some(bucket => Object.values(bucket).some(count => count !== 0))) throw Error("unexpected_application_csp_violation");
  if (canaries && (state.mode !== "enforced-fixture" || state.probe_script_requests !== 1 || !state.canaries_completed
    || REQUIRED.some(name => state.canary.enforce[name] !== 1) || Object.keys(state.canary.enforce).length !== REQUIRED.length
    || Object.keys(state.canary.report).length)) throw Error("csp_canary_coverage_invalid");
}

export async function runCspCanaries(ctx) {
  if (ctx.csp.mode !== "enforced-fixture") throw Error("csp_canary_mode_invalid");
  ctx.stage = "csp_dom_canaries";
  await ctx.evaluate(`(()=>{const s=document.createElement('script');s.src=${JSON.stringify(CSP_PROBE_PATH)};document.head.appendChild(s);return true})()`);
  await ctx.waitFor("window.__aquaCspProbeResult?.complete===true", "csp_dom_canaries_finished");
  await ctx.check("document CSP blocks actual inline scripts handlers evaluation and base changes", "Object.values(window.__aquaCspProbeResult).every(value=>value===true)");
  // Binding events and the completion response share the browser protocol queue.
  ctx.csp.canaries_completed = true;
  assertCspCoverage(ctx.csp, { canaries: true });
  ctx.results.push({ check: "CSP canaries cover script connect image frame object and base enforcement without external transport", passed: true });
}
