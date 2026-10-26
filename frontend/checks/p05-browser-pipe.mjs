// CDP over anonymous pipes only. Reports retain fixed lifecycle metadata, never
// expressions, URLs, payloads, raw frames, browser errors or stream exceptions.
const MAX_FRAME = 16 * 1024 * 1024, MAX_PENDING = 64;
const CLOSING_FETCH = new Set(["Fetch.fulfillRequest", "Fetch.continueRequest", "Fetch.failRequest"]);
const FRAME_KINDS = new Set(["non_object", "response_shape", "response_payload_shape", "response_session_missing", "response_session_mismatch", "event_shape"]);
const METHODS = new Set([
  "Browser.getVersion", "Browser.close", "Target.getTargets", "Target.attachToTarget", "Target.createTarget", "Target.closeTarget",
  "Page.enable", "Page.navigate", "Page.captureScreenshot", "Page.addScriptToEvaluateOnNewDocument", "Page.bringToFront",
  "Network.enable", "Network.getCookies", "Runtime.enable", "Runtime.evaluate", "Fetch.enable", "Fetch.fulfillRequest", "Fetch.continueRequest", "Fetch.failRequest",
  "Emulation.setDeviceMetricsOverride", "Emulation.setEmulatedMedia", "Input.dispatchKeyEvent", "DOM.enable", "DOM.getDocument", "DOM.querySelector", "CSS.enable", "CSS.getPlatformFontsForNode",
]);
const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
const protocolClass = (error) => !record(error) || typeof error.message !== "string" ? "none"
  : error.code === -32001 && error.message === "Session with given id not found." ? "session_not_found"
  : /Invalid InterceptionId|No resource with given identifier/.test(error.message) ? "request_no_longer_exists"
  : /Session with given id not found|Target closed|Session closed/.test(error.message) ? "target_no_longer_exists" : "other_protocol_error";
async function waitForClose(closed, milliseconds) {
  let timer;
  try { await Promise.race([closed, new Promise((resolve) => { timer = setTimeout(resolve, milliseconds); })]); }
  finally { clearTimeout(timer); }
}
const STAGES = new Set(["browser_startup", "browser_command", "browser_cleanup"]);
const REASONS = new Set(["browser_closed", "browser_start_failed", "browser_pipe_closed", "browser_suite_deadline", "browser_protocol_deadline",
  "browser_protocol_frame_bound", "browser_protocol_invalid_json", "browser_protocol_invalid_frame", "browser_protocol_unmatched_response",
  "browser_protocol_pending_bound", "browser_protocol_method_rejected", "browser_event_failed"]);

export class BrowserPipe {
  constructor(child, { session = () => null, deadline = performance.now() + 240000, startupMs = 30000, commandMs = 7000 } = {}) {
    if (![deadline, startupMs, commandMs].every(Number.isFinite) || startupMs <= 0 || startupMs > 30000 || commandMs <= 0 || commandMs > 7000) throw new Error("browser_deadline_invalid");
    this.child = child; this.session = session; this.deadline = deadline; this.startupMs = startupMs; this.commandMs = commandMs;
    this.pending = new Map(); this.sequence = 0; this.buffer = Buffer.alloc(0); this.onEvent = () => {};
    this.failure = null; this.diagnostic = null; this.cleanupFailure = null; this.stopped = false; this.drained = false; this.stopping = false; this.startupSent = false;
    this.closeKind = null;
    this.closed = new Promise((resolve) => child.once("close", (code, signal) => {
      this.stopped = true; this.drained = true;
      this.closeKind = code === 0 && signal === null ? "normal_exit" : typeof signal === "string" && signal.length ? "signal_exit" : "abnormal_exit";
      if (this.stopping && this.closeKind !== "normal_exit") this.cleanupFailed(this.failure || "browser_cleanup_abnormal_exit");
      resolve(); this.fail("browser_closed", null, !this.stopping);
    }));
    // Exit alone is not a pipe boundary: the final response can still be buffered.
    child.once("exit", () => { this.stopped = true; });
    child.once("error", () => this.fail("browser_start_failed"));
    child.stdio[3].on("error", () => this.fail("browser_pipe_closed"));
    child.stdio[4].on("error", () => this.fail("browser_pipe_closed"));
    child.stdio[4].on("end", () => {
      // Chrome may close its transport instead of replying to Browser.close.
      // Only that explicit shutdown command may finish via a normal process close.
      if (!this.buffer.length && this.stopping && [...this.pending.values()].every((task) => task.method === "Browser.close")) return;
      if (this.buffer.length || this.pending.size) this.fail("browser_pipe_closed");
    });
    child.stdio[4].on("data", (chunk) => this.receive(chunk));
  }
  fail(reason = "browser_closed", task = null, diagnostic = true) {
    if (this.failure) return;
    if (!REASONS.has(reason)) reason = "browser_closed";
    this.failure = reason;
    if (diagnostic) {
      task ||= this.pending.values().next().value;
      this.diagnostic ||= this.describe(reason, task);
    }
    for (const item of this.pending.values()) { clearTimeout(item.timer); item.reject(new Error(reason)); }
    this.pending.clear(); this.buffer = Buffer.alloc(0);
    if (!this.stopped) this.child.kill();
  }
  describe(reason, task) {
    return { reason, stage: STAGES.has(task?.stage) ? task.stage : "browser_command", method: METHODS.has(task?.method) ? task.method : null,
      pending_count: this.pending.size, ...(task ? { elapsed_ms: Math.max(0, Math.round(performance.now() - task.started)), timeout_ms: task.timeout } : {}) };
  }
  cleanupFailed(reason) {
    this.cleanupFailure ||= reason;
    this.diagnostic ||= { reason, stage: "browser_cleanup", method: "Browser.close", pending_count: this.pending.size,
      ...(this.closeKind ? { exit_kind: this.closeKind } : {}) };
  }
  invalidFrame(kind, task = this.pending.values().next().value, error = null) {
    // Both fields are fixed enums derived here; no frame text or IDs survive.
    this.diagnostic ||= { ...this.describe("browser_protocol_invalid_frame", task), invalid_frame_kind: FRAME_KINDS.has(kind) ? kind : "unknown_frame", protocol_error_class: protocolClass(error) };
    return this.fail("browser_protocol_invalid_frame", task);
  }
  receive(chunk) {
    if (this.failure) return;
    this.buffer = Buffer.concat([this.buffer, chunk]);
    let end;
    while ((end = this.buffer.indexOf(0)) !== -1) {
      if (end > MAX_FRAME) return this.fail("browser_protocol_frame_bound");
      const raw = this.buffer.subarray(0, end); this.buffer = this.buffer.subarray(end + 1);
      if (!raw.length) continue;
      let message;
      try { message = JSON.parse(raw.toString("utf8")); } catch { return this.fail("browser_protocol_invalid_json"); }
      if (!record(message)) return this.invalidFrame("non_object");
      if (Object.hasOwn(message, "id")) {
        const task = this.pending.get(message.id);
        if (!Number.isSafeInteger(message.id) || !task) return this.fail("browser_protocol_unmatched_response");
        if (Object.hasOwn(message, "result") === Object.hasOwn(message, "error")) return this.invalidFrame("response_shape", task, message.error);
        if (message.error ? !record(message.error) || typeof message.error.message !== "string" : !record(message.result)) return this.invalidFrame("response_payload_shape", task, message.error);
        // Chromium emits SessionNotFound on its root session after a flattened
        // child is removed. Only this exact correlated shutdown Fetch rejection
        // may omit sessionId; it never becomes a successful command response.
        const shutdownSessionMissing = this.stopping && Boolean(task.target) && CLOSING_FETCH.has(task.method)
          && !Object.hasOwn(message, "sessionId") && protocolClass(message.error) === "session_not_found";
        if ((message.sessionId ?? null) !== task.target && !shutdownSessionMissing) return this.invalidFrame(Object.hasOwn(message, "sessionId") ? "response_session_mismatch" : "response_session_missing", task, message.error);
        this.pending.delete(message.id); clearTimeout(task.timer);
        if (message.error) {
          const error = new Error("browser_protocol_failed");
          const classification = protocolClass(message.error);
          error.protocolReason = classification === "session_not_found" ? "target_no_longer_exists" : classification;
          error.canceled = error.protocolReason === "request_no_longer_exists";
          error.shutdownSessionMissing = shutdownSessionMissing;
          error.browserDiagnostic = { ...this.describe("browser_protocol_failed", task), protocol_reason: error.protocolReason };
          task.reject(error);
        } else task.resolve(message.result);
      } else {
        if (typeof message.method !== "string" || message.method.length > 128 || !/^[A-Za-z]+\.[A-Za-z]+$/.test(message.method)
          || (Object.hasOwn(message, "params") && !record(message.params))) return this.invalidFrame("event_shape");
        try { this.onEvent(message); } catch { return this.fail("browser_event_failed"); }
      }
      if (this.failure) return;
    }
    if (this.buffer.length > MAX_FRAME) this.fail("browser_protocol_frame_bound");
  }
  ready() {
    if (this.startupSent) return Promise.reject(new Error("browser_startup_already_requested"));
    this.startupSent = true;
    // Only this handshake gets the cold-process allowance. It is sent once,
    // shares the suite deadline, and never retries a command or browser journey.
    return this.request("Browser.getVersion", {}, null, this.startupMs, "browser_startup");
  }
  send(method, params = {}, target = this.session()) {
    return this.request(method, params, target || null, this.commandMs, this.stopping ? "browser_cleanup" : "browser_command");
  }
  request(method, params, target, maximum, stage) {
    if (this.failure || this.stopped) return Promise.reject(new Error(this.failure || "browser_closed"));
    const task = { method, stage, target, started: performance.now(), timeout: Math.min(maximum, Math.max(0, this.deadline - performance.now())) };
    if (!METHODS.has(method)) { this.fail("browser_protocol_method_rejected", task); return Promise.reject(new Error(this.failure)); }
    if (this.pending.size >= MAX_PENDING) { this.fail("browser_protocol_pending_bound", task); return Promise.reject(new Error(this.failure)); }
    if (task.timeout <= 0) { this.fail("browser_protocol_deadline", task); return Promise.reject(new Error(this.failure)); }
    return new Promise((resolve, reject) => {
      const id = ++this.sequence;
      task.resolve = resolve; task.reject = reject;
      task.timer = setTimeout(() => this.fail("browser_protocol_deadline", task), task.timeout);
      this.pending.set(id, task);
      try {
        const frame = JSON.stringify({ id, method, params, ...(target ? { sessionId: target } : {}) });
        if (Buffer.byteLength(frame) > MAX_FRAME) return this.fail("browser_protocol_frame_bound", task);
        this.child.stdio[3].write(frame + "\0", (error) => { if (error) this.fail("browser_pipe_closed", task); });
      } catch { this.fail("browser_pipe_closed", task); }
    });
  }
  async stop() {
    this.stopping = true;
    // An idle transport failure still invalidates the gate, even when it had no
    // pending caller to reject. Existing primary diagnostics remain untouched.
    if (this.failure) this.cleanupFailed(this.failure);
    if (!this.stopped && !this.failure) {
      // The close command gets one second; process/profile drainage below has
      // its own single grace window, sharing the original suite deadline.
      try { await this.request("Browser.close", {}, null, 1000, "browser_cleanup"); }
      catch {
        if (!(this.drained && this.closeKind === "normal_exit" && this.failure === "browser_closed")) this.cleanupFailed(this.failure || "browser_cleanup_rejected");
      }
    }
    const gracefulMs = Math.min(5000, Math.max(0, this.deadline - performance.now()));
    if (!this.drained && gracefulMs > 0) await waitForClose(this.closed, gracefulMs);
    if (!this.stopped) {
      this.cleanupFailed("browser_cleanup_forced_kill");
      this.child.kill("SIGKILL"); await waitForClose(this.closed, 1500);
    }
    if (!this.drained || !this.stopped) this.cleanupFailed("browser_cleanup_unconfirmed");
    this.fail("browser_closed", null, false);
    return this.stopped;
  }
}
