import assert from "node:assert/strict";
import test from "node:test";
import { FixtureBridge } from "./p05-browser-bridge.mjs";

const RUN = "aqua-p05-browser-" + "a".repeat(24);
const CANARY = "synthetic-secret-must-never-enter-diagnostics";
const terminal = (id = "finish", passed = false) => ({
  id, kind: "finished", status: passed ? "passed" : "failed",
  report: { run: RUN, status: passed ? "passed" : "failed", step: "worker_start", cleanup: "removed_and_absence_confirmed", remaining_ids: [], ...(passed ? {} : { failure: "fixture_operation_failed_details_redacted" }) },
});
const emit = (value) => `process.stdout.write(${JSON.stringify(JSON.stringify(value) + "\n")});`;
const ready = emit({ kind: "ready", schema_version: 6 });

function fixture(t, source) {
  // A disposable local Node subprocess exercises actual pipe framing without
  // Docker, HTTP, provider credentials or any production source/environment.
  const bridge = new FixtureBridge(process.execPath, ["--eval", source, "--"], "http://127.0.0.1:54321");
  t.after(async () => {
    bridge.process.stdin.end();
    if (bridge.process.exitCode === null) bridge.process.kill();
    await bridge.closed;
  });
  return bridge;
}

test("fixture startup failure retains the sanitized terminal cleanup report", { timeout: 5000 }, async (t) => {
  const bridge = fixture(t, emit(terminal()));
  await assert.rejects(bridge.ready, { message: "bridge_startup_failed" });
  await bridge.closed;
  assert.equal(bridge.finished.report.step, "worker_start");
  assert.equal(bridge.finished.report.cleanup, "removed_and_absence_confirmed");
  assert.deepEqual(bridge.finished.report.remaining_ids, []);
  assert.equal(bridge.finished.status, "failed");
  assert.throws(() => bridge.send("finish"), { message: "bridge_closed" });
});

test("startup exception diagnostics omit raw text and preserve following cleanup in one chunk", { timeout: 5000 }, async (t) => {
  const error = { kind: "error", category: "ModuleNotFoundError", stage: "app_import", module: "httpx", message: CANARY, traceback: CANARY };
  const frames = JSON.stringify(error) + "\n" + JSON.stringify(terminal()) + "\n";
  const bridge = fixture(t, `process.stdout.write(${JSON.stringify(frames)});`);
  await assert.rejects(bridge.ready, { message: "bridge_startup_failed" });
  await bridge.closed;
  assert.deepEqual(bridge.diagnostic, { kind: "error", category: "ModuleNotFoundError", stage: "app_import", module: "httpx" });
  assert.equal(bridge.finished.report.cleanup, "removed_and_absence_confirmed");
  assert.equal(JSON.stringify({ diagnostic: bridge.diagnostic, finished: bridge.finished }).includes(CANARY), false);
});

test("bridge matches real request IDs and receives final cleanup before child close", { timeout: 5000 }, async (t) => {
  const bridge = fixture(t, ready + `process.stdin.on('data', chunk => {const item=JSON.parse(chunk);const reply=item.kind==='finish'?${JSON.stringify(terminal(null, true))}:{status:200};reply.id=item.id;process.stdout.write(JSON.stringify(reply)+String.fromCharCode(10),()=>{if(item.kind==='finish')process.exit(0)});});`);
  assert.equal((await bridge.ready).schema_version, 6);
  assert.equal((await bridge.send("request", { path: "/api/auth/me" })).status, 200);
  const finished = await bridge.send("finish");
  await bridge.closed;
  assert.equal(finished.status, "passed");
  assert.equal(finished.report.cleanup, "removed_and_absence_confirmed");
});

test("unknown request IDs still fail while terminal cleanup remains observable", { timeout: 5000 }, async (t) => {
  const frames = JSON.stringify({ id: 999, status: 200 }) + "\n" + JSON.stringify(terminal()) + "\n";
  const bridge = fixture(t, ready + `process.stdin.once('data',()=>process.stdout.write(${JSON.stringify(frames)},()=>process.exit(0)));`);
  await bridge.ready;
  await assert.rejects(bridge.send("request"), { message: "bridge_unmatched_response" });
  await bridge.closed;
  assert.equal(bridge.finished.report.cleanup, "removed_and_absence_confirmed");
  assert.throws(() => bridge.send("request"), { message: "bridge_closed" });
});

test("duplicate ready frames cannot bypass response correlation", { timeout: 5000 }, async (t) => {
  const bridge = fixture(t, ready + `process.stdin.once('data',()=>{${ready}process.exit(0)});`);
  await bridge.ready;
  await assert.rejects(bridge.send("request"), { message: "bridge_unmatched_response" });
});

for (const value of [null, [], CANARY]) {
  test(`bridge rejects non-object JSON frame ${Array.isArray(value) ? "array" : value === null ? "null" : "string"}`, { timeout: 5000 }, async (t) => {
    const bridge = fixture(t, emit(value));
    await assert.rejects(bridge.ready, { message: "bridge_invalid_response" });
    assert.equal(bridge.diagnostic, null);
  });
}

test("invalid JSON fails without disclosing the source frame", { timeout: 5000 }, async (t) => {
  const bridge = fixture(t, `process.stdout.write(${JSON.stringify(CANARY + "\n")});`);
  await assert.rejects(bridge.ready, { message: "bridge_invalid_json" });
  assert.equal(bridge.diagnostic, null);
});

test("oversized output and stderr are bounded without retaining their contents", { timeout: 5000 }, async (t) => {
  for (const [stream, reason] of [["stdout", "bridge_output_bound"], ["stderr", "bridge_stderr_bound"]]) {
    const bridge = fixture(t, `process.${stream}.write('x'.repeat(131073));`);
    await assert.rejects(bridge.ready, { message: reason });
    await bridge.closed;
    assert.equal(bridge.diagnostic, null);
    assert.equal(Object.hasOwn(bridge, "stderr"), false);
  }
});

test("oversized requests are rejected before writing to the fixture", { timeout: 5000 }, async (t) => {
  const bridge = fixture(t, ready + "process.stdin.resume();");
  await bridge.ready;
  assert.throws(() => bridge.send("request", { bodyBase64: "x".repeat(131073) }), { message: "bridge_input_bound" });
  assert.equal(bridge.pending.size, 0);
});

test("terminal diagnostics retain only known metadata and never invent cleanup success", { timeout: 5000 }, async (t) => {
  const value = terminal();
  value.report.worker_error = { category: "ModuleNotFoundError", stage: "app_import", module: CANARY, message: CANARY };
  value.report.step = CANARY;
  value.report.remaining_ids = [CANARY];
  value.report.failure = CANARY;
  value.report.headers = { authorization: CANARY };
  const bridge = fixture(t, emit(value));
  await assert.rejects(bridge.ready, { message: "bridge_startup_failed" });
  assert.equal(JSON.stringify(bridge.diagnostic).includes(CANARY), false);
  assert.equal(Object.hasOwn(bridge.finished.report, "remaining_ids"), false);
  assert.deepEqual(bridge.finished.report.worker_error, { category: "ModuleNotFoundError", stage: "app_import" });
});

test("an explicitly failed finish reply cannot become successful cleanup", { timeout: 5000 }, async (t) => {
  const value = terminal(null);
  value.report.cleanup = "failed";
  value.report.remaining_ids = [RUN + "-pg"];
  const bridge = fixture(t, ready + `process.stdin.once('data',chunk=>{const reply=${JSON.stringify(value)};reply.id=JSON.parse(chunk).id;process.stdout.write(JSON.stringify(reply)+String.fromCharCode(10),()=>process.exit(0));});`);
  await bridge.ready;
  const finished = await bridge.send("finish");
  assert.equal(finished.status, "failed");
  assert.equal(finished.report.cleanup, "failed");
  assert.deepEqual(finished.report.remaining_ids, [RUN + "-pg"]);
});
