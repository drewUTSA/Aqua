import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { spawn } from "node:child_process";
import { PassThrough } from "node:stream";
import test from "node:test";
import { BrowserPipe } from "./p05-browser-pipe.mjs";

const CANARY = "synthetic-secret-never-retain-in-diagnostics";
const encode = (value) => Buffer.from(JSON.stringify(value) + "\0");
function fixture(t, options = {}) {
  const child = new EventEmitter(), requests = [];
  child.stdio = [null, null, null, new PassThrough(), new PassThrough()];
  child.stdio[3].on("data", (chunk) => requests.push(JSON.parse(chunk.toString().slice(0, -1))));
  child.kill = () => { child.emit("exit", null, "SIGTERM"); child.emit("close", null, "SIGTERM"); return true; };
  const client = new BrowserPipe(child, options);
  t.after(() => { client.fail("browser_closed", null, false); child.stdio[3].destroy(); child.stdio[4].destroy(); });
  return { child, client, requests, reply: (value) => child.stdio[4].write(encode(value)) };
}

test("cold startup gets one bounded allowance; later commands retain seven seconds", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client, requests, reply } = fixture(t);
  const ready = client.ready();
  t.mock.timers.tick(8000); // A cold response after the old seven-second failure.
  assert.equal(client.failure, null);
  reply({ id: requests[0].id, result: { product: "Synthetic Chrome" } });
  assert.equal((await ready).product, "Synthetic Chrome");
  await assert.rejects(client.ready(), { message: "browser_startup_already_requested" });
  const command = assert.rejects(client.send("Target.getTargets"), { message: "browser_protocol_deadline" });
  t.mock.timers.tick(6999); assert.equal(client.failure, null);
  t.mock.timers.tick(1); await command;
  assert.equal(requests.length, 2, "no implicit command or journey retry");
  assert.equal(client.diagnostic.stage, "browser_command");
  assert.equal(client.diagnostic.method, "Target.getTargets");
  assert.equal(client.diagnostic.timeout_ms, 7000);
});

test("stalled startup fails at thirty seconds and cleanup never reuses the timed-out pipe", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client, requests } = fixture(t);
  const failure = assert.rejects(client.ready(), { message: "browser_protocol_deadline" });
  t.mock.timers.tick(29999); assert.equal(client.failure, null);
  t.mock.timers.tick(1); await failure;
  assert.equal(client.diagnostic.stage, "browser_startup");
  assert.equal(client.diagnostic.method, "Browser.getVersion");
  assert.equal(client.diagnostic.timeout_ms, 30000);
  assert.equal(await client.stop(), true);
  await assert.rejects(client.send("Browser.close"), { message: "browser_protocol_deadline" });
  assert.equal(requests.length, 1);
});

test("startup allowance cannot extend the remaining overall suite deadline", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client } = fixture(t, { deadline: performance.now() + 1000 });
  const failure = assert.rejects(client.ready(), { message: "browser_protocol_deadline" });
  t.mock.timers.tick(1000); await failure;
  assert.ok(client.diagnostic.timeout_ms > 0 && client.diagnostic.timeout_ms <= 1000);
});

test("split and coalesced frames preserve request/session correlation and events", async (t) => {
  const { client, requests, child } = fixture(t, { session: () => "synthetic-session" });
  const events = []; client.onEvent = (event) => events.push(event.method);
  const first = client.send("Page.enable"), second = client.send("Runtime.enable");
  const data = Buffer.concat([encode({ id: requests[1].id, sessionId: "synthetic-session", result: { second: true } }),
    encode({ method: "Page.loadEventFired", sessionId: "synthetic-session", params: {} }),
    encode({ id: requests[0].id, sessionId: "synthetic-session", result: { first: true } })]);
  child.stdio[4].write(data.subarray(0, 7)); child.stdio[4].write(data.subarray(7));
  assert.deepEqual(await first, { first: true }); assert.deepEqual(await second, { second: true });
  assert.deepEqual(events, ["Page.loadEventFired"]);
});

for (const [label, raw, reason] of [
  ["malformed JSON", Buffer.from(CANARY + "\0"), "browser_protocol_invalid_json"],
  ["array", encode([]), "browser_protocol_invalid_frame"],
  ["missing result", encode({ id: 1 }), "browser_protocol_invalid_frame"],
  ["invalid error", encode({ id: 1, error: CANARY }), "browser_protocol_invalid_frame"],
  ["wrong session", encode({ id: 1, sessionId: CANARY, result: {} }), "browser_protocol_invalid_frame"],
  ["unknown response", encode({ id: 999, result: {} }), "browser_protocol_unmatched_response"],
  ["invalid event", encode({ method: CANARY, params: {} }), "browser_protocol_invalid_frame"],
]) {
  test(`rejects ${label} and clears all pending work without exposing raw material`, async (t) => {
    const { client, child } = fixture(t);
    const pending = [client.send("Runtime.evaluate", { expression: CANARY }), client.send("Network.enable")];
    const checks = pending.map((promise) => assert.rejects(promise, { message: reason }));
    child.stdio[4].write(raw); await Promise.all(checks);
    assert.equal(client.pending.size, 0); assert.equal(client.buffer.length, 0);
    assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
    assert.equal(client.diagnostic.method, "Runtime.evaluate");
    await assert.rejects(client.send("Runtime.enable"), { message: reason });
  });
}

test("duplicate responses fail instead of becoming browser events", async (t) => {
  const { client, requests, reply } = fixture(t);
  const pending = client.send("Page.enable"); reply({ id: requests[0].id, result: {} }); await pending;
  reply({ id: requests[0].id, result: {} });
  assert.equal(client.failure, "browser_protocol_unmatched_response");
});

test("frame and pending-command limits fail closed", async (t) => {
  const oversized = fixture(t), saturated = fixture(t);
  const frameFailure = assert.rejects(oversized.client.ready(), { message: "browser_protocol_frame_bound" });
  oversized.child.stdio[4].write(Buffer.alloc(16 * 1024 * 1024 + 1, 120)); await frameFailure;
  const commands = Array.from({ length: 65 }, () => saturated.client.send("Network.enable"));
  await Promise.all(commands.map((promise) => assert.rejects(promise, { message: "browser_protocol_pending_bound" })));
  assert.equal(saturated.requests.length, 64);
});

test("write, read and spawn errors have fixed redacted diagnostics", async (t) => {
  for (const stream of ["write", "read", "spawn"]) {
    const { client, child } = fixture(t);
    const failed = assert.rejects(client.ready(), { message: stream === "spawn" ? "browser_start_failed" : "browser_pipe_closed" });
    (stream === "spawn" ? child : child.stdio[stream === "write" ? 3 : 4]).emit("error", new Error(CANARY));
    await failed; assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
  }
});

test("exit does not discard the final frame, while close rejects unfinished work", async (t) => {
  const drained = fixture(t), incomplete = fixture(t);
  const ready = drained.client.ready(); drained.child.emit("exit", 0, null);
  drained.reply({ id: drained.requests[0].id, result: { product: "Synthetic" } });
  drained.child.emit("close", 0, null); assert.equal((await ready).product, "Synthetic");
  const failure = assert.rejects(incomplete.client.ready(), { message: "browser_closed" });
  incomplete.child.emit("close", 1, null); await failure;
  assert.equal(incomplete.client.stopped, true);
});

test("canceled navigation errors retain their existing safe classification", async (t) => {
  const { client, requests, reply } = fixture(t);
  for (const [message, protocolReason, canceled] of [["Invalid InterceptionId " + CANARY, "request_no_longer_exists", true],
    ["Session closed " + CANARY, "target_no_longer_exists", false], [CANARY, "other_protocol_error", false]]) {
    const command = client.send("Fetch.continueRequest", { requestId: CANARY });
    reply({ id: requests.at(-1).id, error: { code: -32000, message } });
    await assert.rejects(command, (error) => error.message === "browser_protocol_failed" && error.protocolReason === protocolReason
      && error.canceled === canceled && !JSON.stringify(error).includes(CANARY));
    assert.equal(client.failure, null, "expected lifecycle rejection does not poison the channel");
  }
});

test("unrecognized methods cannot inject diagnostic content", async (t) => {
  const { client } = fixture(t);
  await assert.rejects(client.send(CANARY, { secret: CANARY }), { message: "browser_protocol_method_rejected" });
  assert.equal(client.diagnostic.method, null); assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
});

test("explicit Browser.close may end without a response, with no cleanup failure", async (t) => {
  const { client, child } = fixture(t);
  const stopped = client.stop();
  child.stdio[4].end(); child.emit("exit", 0, null); child.emit("close", 0, null);
  assert.equal(await stopped, true);
  assert.equal(client.diagnostic, null); assert.equal(client.cleanupFailure, null);
});

test("cleanup protocol deadlines remain failures even when killing confirms termination", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client } = fixture(t);
  const stopped = client.stop(); t.mock.timers.tick(1000);
  assert.equal(await stopped, true);
  assert.equal(client.cleanupFailure, "browser_protocol_deadline");
  assert.equal(client.diagnostic.stage, "browser_cleanup");
});

test("Browser.close rejection cannot become clean after an otherwise normal exit", async (t) => {
  const { client, child, requests, reply } = fixture(t);
  const stopped = client.stop();
  reply({ id: requests[0].id, error: { code: -32000, message: CANARY } });
  await Promise.resolve();
  child.emit("exit", 0, null); child.emit("close", 0, null);
  assert.equal(await stopped, true);
  assert.equal(client.cleanupFailure, "browser_cleanup_rejected");
  assert.equal(client.diagnostic.stage, "browser_cleanup");
  assert.equal(client.diagnostic.method, "Browser.close");
  assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
});

test("Browser.close acknowledgement without termination fails at the five-second grace bound", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client, requests, reply } = fixture(t);
  const stopped = client.stop(); reply({ id: requests[0].id, result: {} });
  await Promise.resolve(); t.mock.timers.tick(4999);
  assert.equal(client.cleanupFailure, null); assert.equal(client.stopped, false);
  t.mock.timers.tick(1);
  assert.equal(await stopped, true);
  assert.equal(client.cleanupFailure, "browser_cleanup_forced_kill");
  assert.equal(client.diagnostic.reason, "browser_cleanup_forced_kill");
});

test("acknowledged close can drain normally beyond one second without a retry", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client, child, requests, reply } = fixture(t);
  const stopped = client.stop(); reply({ id: requests[0].id, result: {} });
  await Promise.resolve(); t.mock.timers.tick(1500);
  assert.equal(client.cleanupFailure, null); assert.equal(client.stopped, false);
  child.stdio[4].end(); child.emit("exit", 0, null); child.emit("close", 0, null);
  assert.equal(await stopped, true);
  assert.equal(client.diagnostic, null); assert.equal(client.cleanupFailure, null);
  assert.equal(requests.length, 1, "graceful drainage never retries Browser.close");
});

test("process drain grace cannot extend the remaining overall deadline", async (t) => {
  t.mock.timers.enable({ apis: ["setTimeout"] });
  const { client, requests, reply } = fixture(t, { deadline: performance.now() + 1000 });
  const stopped = client.stop(); reply({ id: requests[0].id, result: {} });
  await Promise.resolve(); t.mock.timers.tick(1000);
  assert.equal(await stopped, true);
  assert.equal(client.cleanupFailure, "browser_cleanup_forced_kill");
});

for (const [label, code, signal, kind] of [["nonzero", 1, null, "abnormal_exit"], ["signal", null, "SIGTERM", "signal_exit"],
  ["unknown", null, null, "abnormal_exit"], ["untrusted signal", null, CANARY, "signal_exit"]]) {
  test(`explicit shutdown fails on ${label} exit without logging raw exit material`, async (t) => {
    const { client, child } = fixture(t);
    const stopped = client.stop(); child.stdio[4].end();
    child.emit("exit", code, signal); child.emit("close", code, signal);
    assert.equal(await stopped, true);
    assert.equal(client.cleanupFailure, "browser_cleanup_abnormal_exit");
    assert.equal(client.diagnostic.exit_kind, kind);
    assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
  });
}

test("idle channel failure is surfaced by stop without replacing the primary diagnostic", async (t) => {
  const { client, child } = fixture(t);
  child.stdio[4].emit("error", new Error(CANARY));
  assert.equal(client.pending.size, 0);
  const primary = client.diagnostic;
  assert.equal(await client.stop(), true);
  assert.equal(client.cleanupFailure, "browser_pipe_closed");
  assert.equal(client.diagnostic, primary);
  assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
});

test("normal shutdown correlates a sessionless SessionNotFound Fetch rejection without resolving it", async (t) => {
  const { client, child, requests, reply } = fixture(t, { session: () => "synthetic-session" });
  const stopped = client.stop(); reply({ id: requests[0].id, result: {} }); await Promise.resolve();
  const fetch = client.send("Fetch.fulfillRequest", { requestId: CANARY });
  const rejected = assert.rejects(fetch, (error) => error.message === "browser_protocol_failed" && error.protocolReason === "target_no_longer_exists"
    && error.shutdownSessionMissing === true && !JSON.stringify(error).includes(CANARY));
  reply({ id: requests.at(-1).id, error: { code: -32001, message: "Session with given id not found." } });
  await rejected; assert.equal(client.failure, null);
  child.emit("exit", 0, null); child.emit("close", 0, null); assert.equal(await stopped, true);
  assert.equal(client.cleanupFailure, null); assert.equal(client.diagnostic, null);
});

for (const [label, fields, expected] of [["wrong session", { sessionId: CANARY }, "browser_protocol_invalid_frame"],
  ["null session", { sessionId: null }, "browser_protocol_invalid_frame"], ["unknown id", { id: 999 }, "browser_protocol_unmatched_response"],
  ["missing id", { id: undefined }, "browser_protocol_invalid_frame"], ["result and error", { result: {} }, "browser_protocol_invalid_frame"],
  ["wrong error code", { error: { code: -32000, message: "Session with given id not found." } }, "browser_protocol_invalid_frame"]]) {
  test(`shutdown session exception rejects ${label} and retains only fixed diagnostics`, async (t) => {
    const { client, requests, reply } = fixture(t, { session: () => "synthetic-session" });
    const stopped = client.stop(); reply({ id: requests[0].id, result: {} }); await Promise.resolve();
    const rejected = assert.rejects(client.send("Fetch.fulfillRequest", { requestId: CANARY }), { message: expected });
    reply({ id: requests.at(-1).id, error: { code: -32001, message: "Session with given id not found." }, ...fields });
    await rejected; await stopped;
    assert.equal(client.cleanupFailure, expected);
    assert.equal(JSON.stringify(client.diagnostic).includes(CANARY), false);
    if (expected === "browser_protocol_invalid_frame") assert.ok(client.diagnostic.invalid_frame_kind);
  });
}

test("sessionless Fetch errors remain invalid before shutdown", async (t) => {
  const { client, requests, reply } = fixture(t, { session: () => "synthetic-session" });
  const rejected = assert.rejects(client.send("Fetch.fulfillRequest"), { message: "browser_protocol_invalid_frame" });
  reply({ id: requests[0].id, error: { code: -32001, message: "Session with given id not found." } }); await rejected;
  assert.equal(client.diagnostic.invalid_frame_kind, "response_session_missing");
  assert.equal(client.diagnostic.protocol_error_class, "session_not_found");
});

test("real anonymous child pipes drain a final response before close", { timeout: 5000 }, async (t) => {
  const source = `const fs=require('node:fs');const input=fs.createReadStream(null,{fd:3});let data='';input.on('data',chunk=>{data+=chunk;let end;while((end=data.indexOf(String.fromCharCode(0)))>=0){const request=JSON.parse(data.slice(0,end));data=data.slice(end+1);fs.writeSync(4,JSON.stringify({id:request.id,result:{product:'Synthetic Chrome'}})+String.fromCharCode(0));process.exit(0)}});`;
  const child = spawn(process.execPath, ["--eval", source], { windowsHide: true, stdio: ["ignore", "ignore", "ignore", "pipe", "pipe"] });
  const client = new BrowserPipe(child);
  t.after(async () => { await client.stop(); });
  assert.equal((await client.ready()).product, "Synthetic Chrome");
  await client.closed; assert.equal(client.stopped, true);
});
