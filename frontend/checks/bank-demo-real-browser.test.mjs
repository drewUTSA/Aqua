import assert from "node:assert/strict";
import test from "node:test";
import { BankDemoResponseGate, bankRealKey, bankRealMode, bankRealCleanupConfirmed } from "./bank-demo-real-browser-checks.mjs";

const request = { method: "POST", url: "http://127.0.0.1:12345/api/v1/bank-demo/reports" };
const response = raw => ({ status: 200, bodyBase64: Buffer.from(raw ?? '{"synthetic":true}').toString("base64") });
function clock() {
  let at = 0, timer = null;
  return { gate: new BankDemoResponseGate({ now: () => at, setTimer: fn => { timer = fn; return 1; }, clearTimer: () => { timer = null; } }),
    at(value) { at = value; }, expire() { timer?.(); }, hasTimer() { return timer !== null; } };
}

test("real bank journey is explicit and cannot borrow the larger analysis fixture allowance", () => {
  assert.equal(bankRealMode(null, false), false); assert.equal(bankRealMode(null, true), false);
  assert.equal(bankRealMode("bank-demo", false), true);
  for (const pair of [["bank-demo", true], ["all", false], ["manager", false], [undefined, false], [null, "false"]]) assert.throws(() => bankRealMode(...pair), /real_bank_fixture_mode_invalid/);
});
test("real keyboard dispatch preserves native Enter character and denies arbitrary keys", async () => {
  const frames = [], send = async (...args) => { frames.push(args); };
  await bankRealKey(send, "Enter");
  assert.equal(frames.length, 2);
  assert.ok(frames.every(([method, params]) => method === "Input.dispatchKeyEvent" && params.text === "\r" && params.windowsVirtualKeyCode === 13));
  for (const key of ["Tab", "Escape", "Home", "ArrowDown"]) await bankRealKey(send, key);
  assert.equal(frames.length, 10); assert.ok(frames.slice(2).every(([, params]) => !Object.hasOwn(params, "text")));
  await assert.rejects(bankRealKey(send, "SECRET-CANARY"), /real_bank_key_invalid/); assert.equal(frames.length, 10);
});
test("one real computed response is held until explicit release while unrelated requests pass", async () => {
  const { gate, hasTimer } = clock(); let deliveries = 0;
  assert.equal(gate.capture(request, response(), () => { deliveries++; }), false);
  gate.arm();
  assert.equal(gate.capture({ method: "GET", url: "http://127.0.0.1:12345/api/v1/bank-demo/context" }, response(), () => {}), false);
  assert.equal(gate.capture({ method: "POST", url: "http://127.0.0.1:12345/api/auth/logout" }, response(), () => {}), false);
  assert.equal(gate.capture(request, response(), () => { deliveries++; }), true);
  assert.equal(deliveries, 0); assert.equal(gate.snapshot().remaining, 1); assert.equal(hasTimer(), true);
  assert.throws(() => gate.arm(), /real_bank_hold_capacity/);
  await gate.release(); assert.equal(deliveries, 1); assert.equal(hasTimer(), false);
  assert.deepEqual(gate.snapshot(), { captured: 1, released: 1, remaining: 0, armed: false, abandoned: 0, failed: false, closed: false });
  await assert.rejects(gate.release(), /real_bank_hold_missing/); assert.equal(deliveries, 1);
  gate.close(); assert.throws(() => gate.arm(), /real_bank_gate_closed/);
});
test("hold deadlines discard the payload and remain failures even when a timer runs late", async () => {
  for (const timer of [false, true]) {
    const c = clock(); let delivered = false; c.gate.arm(); c.gate.capture(request, response(), () => { delivered = true; });
    c.at(4000); if (timer) c.expire();
    await assert.rejects(c.gate.release(), /real_bank_held_response_deadline/);
    assert.equal(delivered, false); assert.equal(c.gate.snapshot().remaining, 0); assert.equal(c.gate.snapshot().abandoned, 1);
    c.gate.close(); assert.equal(c.gate.snapshot().failed, true);
  }
});
test("invalid or backwards clocks cannot extend the finite hold", async () => {
  for (const at of [NaN, Infinity, -1, "0"]) {
    const c = clock(); c.at(at); c.gate.arm(); assert.throws(() => c.gate.capture(request, response(), () => {}), /real_bank_gate_clock_invalid/);
    assert.equal(c.gate.snapshot().captured, 0); c.gate.close();
  }
  const c = clock(); c.at(10); c.gate.arm(); c.gate.capture(request, response(), () => {}); c.at(9);
  await assert.rejects(c.gate.release(), /real_bank_held_response_deadline/); assert.equal(c.gate.snapshot().failed, true);
});
test("response, origin and getter adversaries fail before a held payload is admitted", () => {
  const secret = "PRIVATE-CANARY-URL-TOKEN";
  const cases = [
    [{ ...request, url: "https://aqua-ai.us/api/v1/bank-demo/reports" }, response()],
    [{ ...request, url: "http://127.0.0.1:12345/api/v1/bank-demo/reports?role=manager" }, response()],
    [{ ...request, url: "http://127.0.0.1:80/api/v1/bank-demo/reports" }, response()],
    [request, response("x".repeat(16385))], [request, { ...response(), status: 403 }],
    [request, { status: 200, bodyBase64: "%%%" }], [request, { status: 200, bodyBase64: "YR==" }],
    [{ get method() { throw Error(secret); } }, response()], [request, { get bodyBase64() { throw Error(secret); }, status: 200 }],
    [{ ...request, url: { toString() { throw Error(secret); } } }, response()], [null, response()], [request, null],
  ];
  for (const [req, result] of cases) {
    const { gate } = clock(); gate.arm();
    assert.throws(() => gate.capture(req, result, () => {}), error => error.message.startsWith("real_bank_hold_") && !String(error).includes(secret));
    assert.equal(gate.snapshot().captured, 0); assert.ok(!JSON.stringify(gate.snapshot()).includes(secret)); gate.close();
  }
});
test("exact body cap is accepted and fixed metadata never serializes payloads or tokens", async () => {
  const { gate } = clock(), secret = "SECRET-PROOF-CANARY";
  gate.arm(); gate.capture(request, response(secret.padEnd(16384, "x")), () => {});
  assert.equal(JSON.stringify(gate), "{}"); assert.ok(!JSON.stringify(gate.snapshot()).includes(secret));
  await gate.release(); gate.close(); assert.equal(gate.snapshot().failed, false);
});
test("unreleased or merely armed work cannot be hidden by cleanup", () => {
  for (const capture of [false, true]) {
    const { gate } = clock(); gate.arm(); if (capture) gate.capture(request, response(), () => {});
    gate.close(); gate.close(); assert.equal(gate.snapshot().abandoned, 1); assert.equal(gate.snapshot().failed, true);
    assert.equal(gate.snapshot().remaining, 0); assert.equal(gate.snapshot().armed, false);
  }
});
test("whole-run response holding has a fixed four-capture ceiling without retries", async () => {
  const { gate } = clock(); let deliveries = 0;
  for (let index = 0; index < 4; index++) { gate.arm(); gate.capture(request, response(), () => { deliveries++; }); await gate.release(); }
  assert.throws(() => gate.arm(), /real_bank_hold_capacity/); assert.equal(deliveries, 4); assert.equal(gate.snapshot().captured, 4); gate.close();
});
test("top-level hold cleanup requires closed healthy accounting and rejects abandoned work", async () => {
  const { gate } = clock();
  assert.equal(bankRealCleanupConfirmed(gate.snapshot()), false);
  gate.arm(); gate.capture(request, response(), () => {}); await gate.release(); gate.close();
  const clean = gate.snapshot(); assert.equal(bankRealCleanupConfirmed(clean), true);
  for (const changed of [{ failed: true }, { abandoned: 1 }, { remaining: 1 }, { armed: true }, { closed: false }, { released: 0 }, { captured: 5, released: 5 }]) assert.equal(bankRealCleanupConfirmed({ ...clean, ...changed }), false);
  for (const value of [null, undefined, {}, { closed: true }]) assert.equal(bankRealCleanupConfirmed(value), false);
});
