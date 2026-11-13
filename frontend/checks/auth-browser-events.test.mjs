import assert from "node:assert/strict";
import test from "node:test";
import { attachAuthBrowserEvents, authDeadline, AUTH_DEADLINE_MS } from "../src/services/authBrowserEvents.js";

function fixture(Channel = null, canRefresh = () => true) {
  const target = new EventTarget(), page = new EventTarget(), calls = [];
  page.visibilityState = "visible";
  let instant = 0;
  const events = attachAuthBrowserEvents({ target, page, Channel, now: () => instant, canRefresh,
    onRefresh: (value) => calls.push(["refresh", value]), onLock: () => calls.push(["lock"]), onOffline: () => calls.push(["offline"]) });
  return { target, page, calls, events, advance: (value) => { instant += value; } };
}
function pageshow(target, persisted) {
  const event = new Event("pageshow"); Object.defineProperty(event, "persisted", { value: persisted }); target.dispatchEvent(event);
}

test("storage-denied BroadcastChannel does not disable recovery events", () => {
  class Denied { constructor() { throw new DOMException("Denied", "SecurityError"); } }
  const f = fixture(Denied);
  f.target.dispatchEvent(new Event("online"));
  assert.deepEqual(f.calls, [["refresh", undefined]]);
  assert.doesNotThrow(() => f.events.notify()); f.events.dispose();
});
test("mobile page-cache restore rechecks even inside the foreground debounce", () => {
  const f = fixture();
  pageshow(f.target, false); assert.equal(f.calls.length, 0);
  pageshow(f.target, true); assert.equal(f.calls.length, 1);
  f.target.dispatchEvent(new Event("focus")); assert.equal(f.calls.length, 1);
  f.advance(10000); f.page.dispatchEvent(new Event("visibilitychange")); assert.equal(f.calls.length, 2);
  f.events.dispose();
});
test("hidden reconnect waits for visibility and an offline event locks through its callback", () => {
  const f = fixture(); f.page.visibilityState = "hidden";
  f.target.dispatchEvent(new Event("online")); assert.equal(f.calls.length, 0);
  f.page.visibilityState = "visible"; f.page.dispatchEvent(new Event("visibilitychange"));
  f.target.dispatchEvent(new Event("offline"));
  assert.deepEqual(f.calls, [["refresh", undefined], ["offline"]]); f.events.dispose();
});
test("ordinary focus does not discard a signed-out form but page restore checks authority", () => {
  const f = fixture(null, () => false); f.advance(20000);
  f.target.dispatchEvent(new Event("focus")); assert.equal(f.calls.length, 0);
  pageshow(f.target, true); assert.equal(f.calls.length, 1); f.events.dispose();
});
test("a backward device-clock correction does not trap foreground revalidation", () => {
  const f = fixture(); f.advance(9999);
  f.target.dispatchEvent(new Event("focus")); assert.equal(f.calls.length, 0);
  f.advance(-10000);
  f.target.dispatchEvent(new Event("focus")); assert.equal(f.calls.length, 1);
  f.events.dispose();
});
test("cross-tab traffic is metadata-only and storage failures never escape", () => {
  let instance;
  class Channel { constructor() { instance = this; } postMessage(value) { this.value = value; } close() { throw new Error("closed"); } }
  const f = fixture(Channel);
  instance.onmessage({ data: { type: "changed", token: "PRIVATE" } });
  instance.onmessage({ data: { type: "changed" } }); instance.onmessage({ data: { type: "locked" } });
  assert.deepEqual(f.calls, [["refresh", { sessionChanged: true }], ["lock"]]);
  f.events.notify(); assert.deepEqual(instance.value, { type: "changed" });
  instance.postMessage = () => { throw new DOMException("Denied", "SecurityError"); };
  assert.doesNotThrow(() => f.events.notify("locked")); assert.doesNotThrow(() => f.events.dispose());
  f.target.dispatchEvent(new Event("online")); assert.equal(f.calls.length, 2);
});

for (const scenario of ["expires", "finished", "superseded", "caller-aborted"]) {
  test(`auth deadline preserves the caller signal and handles ${scenario}`, (t) => {
    let callback, cancelled = 0, notified = 0;
    t.mock.method(globalThis, "setTimeout", (fn, milliseconds) => { callback = fn; assert.equal(milliseconds, 30000); return 1; });
    t.mock.method(globalThis, "clearTimeout", () => { cancelled++; });
    const controller = new AbortController(), signal = controller.signal;
    const finish = authDeadline(controller, () => scenario !== "superseded", () => { notified++; });
    assert.equal(AUTH_DEADLINE_MS, 30000); assert.equal(signal, controller.signal);
    if (scenario === "finished") finish();
    if (scenario === "caller-aborted") controller.abort();
    callback();
    assert.equal(notified, scenario === "expires" ? 1 : 0);
    assert.equal(signal.aborted, ["expires", "caller-aborted"].includes(scenario));
    finish(); assert.ok(cancelled >= 1);
  });
}
