// Bounded JSONL fixture transport. Terminal startup reports are failures, but
// their allowlisted lifecycle metadata must survive so cleanup can be verified.
import { spawn } from "node:child_process";

const MAX_FRAME = 131072;
const STEPS = new Set(["images", "socket_volume", "postgres_create", "postgres_ready", "app_roles", "worker_create", "source_copy", "worker_start"]);
const STAGES = new Set(["before_start", "environment", "app_import", "migration", "runtime_configuration", "client_readiness"]);
const CATEGORIES = new Set(["AssertionError", "PermissionError", "FileNotFoundError", "ModuleNotFoundError", "ImportError", "TypeError", "SyntaxError", "RuntimeError", "ValueError", "TimeoutError", "OSError", "fixture_transport_failed_details_redacted"]);
const MODULES = new Set(["main", "psycopg", "fastapi", "httpx", "google", "google.genai", "pydantic", "sqlalchemy", "auth", "storage"]);
const RUN = /^aqua-p05-browser-[a-f0-9]{24}$/;
const record = (value) => value !== null && typeof value === "object" && !Array.isArray(value);

function safeError(value) {
  if (!record(value)) return {};
  return {
    ...(CATEGORIES.has(value.category) ? { category: value.category } : {}),
    ...(STAGES.has(value.stage) ? { stage: value.stage } : {}),
    ...(value.module === null || MODULES.has(value.module) ? { module: value.module } : {}),
  };
}

function finishedReport(value) {
  const report = record(value.report) ? value.report : {};
  const run = typeof report.run === "string" && RUN.test(report.run) ? report.run : null;
  const names = run ? new Set([`${run}-pg`, `${run}-api`, `${run}-socket`]) : new Set();
  const remaining = run && Array.isArray(report.remaining_ids) && report.remaining_ids.length <= 3 && report.remaining_ids.every((name) => names.has(name)) ? report.remaining_ids : null;
  return {
    kind: "finished",
    status: ["passed", "failed"].includes(value.status) ? value.status : "invalid",
    report: {
      ...(run ? { run } : {}),
      ...(["passed", "failed"].includes(report.status) ? { status: report.status } : {}),
      ...(STEPS.has(report.step) ? { step: report.step } : {}),
      ...(["failed", "removed_and_absence_confirmed"].includes(report.cleanup) ? { cleanup: report.cleanup } : {}),
      ...(remaining ? { remaining_ids: [...remaining] } : {}),
      ...(report.worker_exit === "unconfirmed_or_nonzero" ? { worker_exit: report.worker_exit } : {}),
      ...(report.failure === "fixture_operation_failed_details_redacted" ? { failure: report.failure } : {}),
      ...(record(report.worker_error) ? { worker_error: safeError(report.worker_error) } : {}),
    },
  };
}

export class FixtureBridge {
  constructor(executable, argv, origin) {
    this.pending = new Map(); this.id = 0; this.buffer = Buffer.alloc(0); this.stderrBytes = 0;
    this.finished = null; this.diagnostic = null; this.failure = null;
    this.process = spawn(executable, [...argv, "--origin", origin], { windowsHide: true, stdio: ["pipe", "pipe", "pipe"] });
    this.closed = new Promise((resolve) => this.process.once("close", resolve));
    this.ready = new Promise((resolve, reject) => {
      this.readyTask = { resolve, reject, timer: setTimeout(() => this.fail("bridge_startup_timeout"), 90000) };
    });
    this.process.stdout.on("data", (chunk) => {
      this.buffer = Buffer.concat([this.buffer, chunk]);
      if (this.buffer.length > MAX_FRAME) return this.fail("bridge_output_bound");
      let end;
      while ((end = this.buffer.indexOf(10)) >= 0) {
        const line = this.buffer.subarray(0, end); this.buffer = this.buffer.subarray(end + 1);
        if (!line.length) continue;
        let response;
        try { response = JSON.parse(line.toString("utf8")); } catch { this.fail("bridge_invalid_json"); continue; }
        if (!record(response)) { this.fail("bridge_invalid_response"); continue; }
        if (response.kind === "finished") {
          this.finished ||= finishedReport(response); this.diagnostic ||= this.finished;
          if (this.readyTask) { this.fail("bridge_startup_failed"); continue; }
        }
        if (response.kind === "error") {
          this.diagnostic ||= { kind: "error", ...safeError(response) };
          this.fail(this.readyTask ? "bridge_startup_failed" : "bridge_operation_failed"); continue;
        }
        if (this.failure) continue; // Never resume after a protocol failure.
        if (response.kind === "ready" && this.readyTask) {
          clearTimeout(this.readyTask.timer); this.readyTask.resolve(response); this.readyTask = null; continue;
        }
        const task = this.pending.get(response.id);
        if (!task) { this.fail("bridge_unmatched_response"); continue; }
        this.pending.delete(response.id); clearTimeout(task.timer);
        if (response.error) task.reject(new Error("bridge_operation_failed"));
        else task.resolve(response.kind === "finished" ? this.finished : response);
      }
    });
    // Never retain stderr or exception text: they may contain request material.
    this.process.stderr.on("data", (chunk) => { this.stderrBytes += chunk.length; if (this.stderrBytes > MAX_FRAME) this.fail("bridge_stderr_bound"); });
    this.process.once("error", () => this.fail("bridge_start_failed"));
    this.process.stdin.on("error", () => this.fail("bridge_pipe_closed"));
    // `close` follows stdout drainage; an `exit` event can precede the final frame.
    this.process.once("close", () => this.fail("bridge_exited"));
  }
  fail(reason) {
    this.failure ||= reason;
    if (this.readyTask) { clearTimeout(this.readyTask.timer); this.readyTask.reject(new Error(this.failure)); this.readyTask = null; }
    for (const task of this.pending.values()) { clearTimeout(task.timer); task.reject(new Error(this.failure)); }
    this.pending.clear();
  }
  send(kind, data = {}, timeout = 20000) {
    if (this.finished || this.failure || this.process.exitCode !== null || this.process.stdin.destroyed) throw new Error("bridge_closed");
    const id = ++this.id, frame = JSON.stringify({ id, kind, ...data });
    if (Buffer.byteLength(frame) > MAX_FRAME) throw new Error("bridge_input_bound");
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => { this.pending.delete(id); reject(new Error("bridge_request_timeout")); }, timeout);
      this.pending.set(id, { resolve, reject, timer }); this.process.stdin.write(frame + "\n");
    });
  }
}
