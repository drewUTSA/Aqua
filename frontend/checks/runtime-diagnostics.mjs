// Pure fixture diagnostics. Never retain event objects, text, URLs or remote IDs.
export const MAX_RUNTIME_RECORDS = 8;
const MAX_COORDINATE = 1000000;
const CLASSES = new Set(["Error", "TypeError", "ReferenceError", "SyntaxError", "RangeError", "EvalError", "URIError", "DOMException"]);
const PHASES = new Set(["setup", "authentication", "visual", "csp_canary", "final_boundary", "cleanup", "unknown"]);
const FAILURE_CATEGORIES = new Set([
  "browser_boundary_failure", "fixture_execution_boundary_invalid", "browser_assertion_failed", "browser_condition_failed",
  "page_evaluation_failed", "unexpected_application_csp_violation", "csp_canary_coverage_invalid", "csp_coverage_failed",
  "cleanup_failed", "cleanup_unconfirmed", "fixture_setup_failed", "fixture_boundary_invalid", "fixture_configuration_invalid",
  "browser_suite_deadline", "browser_protocol_failed", "browser_closed",
]);
const CANARY_PATH = "/__aqua-fixture/csp-probes.js";
const HEX = /^[a-f0-9]{64}$/;
const PATH = /^\/[A-Za-z0-9_./-]{1,200}$/;
const DEFAULT_DOCUMENTS = ["/", "/signin", "/register", "/verify-email", "/registration-sent", "/privacy", "/terms"];

function data(value, key) {
  if (value === null || (typeof value !== "object" && typeof value !== "function")) return undefined;
  try { const descriptor = Object.getOwnPropertyDescriptor(value, key); return descriptor && Object.hasOwn(descriptor, "value") ? descriptor.value : undefined; }
  catch { return undefined; }
}
function record(value) { return value !== null && typeof value === "object" && !Array.isArray(value); }
function coordinate(value) { return Number.isSafeInteger(value) && value >= 0 && value <= MAX_COORDINATE ? value : null; }
function identifier(value) { return Number.isSafeInteger(value) && value >= 0; }
function pathname(value) { return typeof value === "string" && (value === "/" || PATH.test(value)) && !value.split("/").includes(".."); }
const increment = value => value < Number.MAX_SAFE_INTEGER ? value + 1 : value;

export class RuntimeDiagnostics {
  #origin;
  #assets = new Map();
  #documents;
  #canarySha;
  #records = [];
  #pending = new Map();
  #thrown = 0;
  #revoked = 0;
  #matchedRevoked = 0;
  #invalid = false;
  #overflow = false;

  constructor({ origin, assets = [], canarySha256 = null, documentPaths = DEFAULT_DOCUMENTS } = {}) {
    let parsed;
    try { parsed = new URL(origin); } catch { throw Error("runtime_diagnostic_configuration_invalid"); }
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash
      || !Array.isArray(assets) || assets.length > 300 || !Array.isArray(documentPaths) || documentPaths.length > 32
      || documentPaths.some(value => !pathname(value)) || (canarySha256 !== null && !HEX.test(canarySha256))) throw Error("runtime_diagnostic_configuration_invalid");
    this.#origin = parsed.origin;
    this.#documents = new Set(documentPaths);
    this.#canarySha = canarySha256;
    for (const asset of assets) {
      const name = data(asset, "name"), sha = data(asset, "sha256");
      if (!pathname(name) || typeof sha !== "string" || !HEX.test(sha) || this.#assets.has(name)) throw Error("runtime_diagnostic_configuration_invalid");
      this.#assets.set(name, sha);
    }
  }

  #source(value) {
    if (typeof value !== "string" || !value || value.length > 4096) return { sourceKind: "unknown", assetSha256: null };
    let parsed;
    try { parsed = new URL(value); } catch { return { sourceKind: "unknown", assetSha256: null }; }
    if (!["http:", "https:"].includes(parsed.protocol) || parsed.origin !== this.#origin || parsed.username || parsed.password) return { sourceKind: "external_or_opaque", assetSha256: null };
    if (!parsed.search && !parsed.hash && this.#assets.has(parsed.pathname)) return { sourceKind: "approved_asset", assetSha256: this.#assets.get(parsed.pathname) };
    if (!parsed.search && !parsed.hash && parsed.pathname === CANARY_PATH && this.#canarySha !== null) return { sourceKind: "canary_script", assetSha256: this.#canarySha };
    if (this.#documents.has(parsed.pathname)) return { sourceKind: "same_origin_document", assetSha256: null };
    return { sourceKind: "same_origin_unknown", assetSha256: null };
  }

  observeThrown(params, phase = "unknown") {
    // No revocation or diagnostic classification can subtract from this count.
    this.#thrown = increment(this.#thrown);
    if (this.#records.length >= MAX_RUNTIME_RECORDS) { this.#overflow = true; return; }
    const details = data(params, "exceptionDetails");
    if (!record(details)) this.#invalid = true;
    const exception = data(details, "exception"), className = data(exception, "className");
    const frames = data(data(details, "stackTrace"), "callFrames");
    const frame = Array.isArray(frames) && frames.length ? data(frames, "0") : undefined;
    const source = data(frame, "url") ?? data(details, "url");
    const line = coordinate(data(frame, "lineNumber") ?? data(details, "lineNumber"));
    const column = coordinate(data(frame, "columnNumber") ?? data(details, "columnNumber"));
    const item = {
      exceptionClass: typeof className === "string" && CLASSES.has(className) ? className : "unknown",
      ...this.#source(source), line, column,
      phase: PHASES.has(phase) ? phase : "unknown", revoked: false,
    };
    const index = this.#records.push(item) - 1;
    const id = data(details, "exceptionId");
    if (identifier(id)) {
      if (this.#pending.has(id)) this.#invalid = true;
      this.#pending.set(id, index);
    } else this.#invalid = true;
  }

  observeRevoked(params) {
    this.#revoked = increment(this.#revoked);
    const id = data(params, "exceptionId");
    if (!identifier(id)) { this.#invalid = true; return; }
    const index = this.#pending.get(id);
    if (index === undefined) return;
    this.#pending.delete(id);
    this.#records[index].revoked = true;
    this.#matchedRevoked = increment(this.#matchedRevoked);
  }

  snapshot() {
    return {
      thrownCount: this.#thrown, revokedCount: this.#revoked, matchedRevokedCount: this.#matchedRevoked,
      invalid: this.#invalid, overflow: this.#overflow,
      records: this.#records.map(item => ({ ...item })),
    };
  }
}

export function resolveFailure(error, phase) {
  // These fixed phases are independent of the legacy free-form stage label.
  const message = data(error, "message");
  return {
    failure_category: typeof message === "string" && FAILURE_CATEGORIES.has(message) ? message : "browser_fixture_failed",
    failure_stage: PHASES.has(phase) ? phase : "unknown",
  };
}
