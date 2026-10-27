import test from "node:test";
import assert from "node:assert/strict";
import { createPlotlyController } from "../src/components/data/plotlyController.js";
import { buildPlotlyFigure } from "../src/services/plotlyFigure.js";
import { plotlyFixture } from "./plotly-fixture.mjs";

const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const settle = async () => { await new Promise((resolve) => setImmediate(resolve)); };
function harness(load) {
  let next = 0, resize, disconnected = 0; const frames = new Map(), calls = [], statuses = [];
  const node = { isConnected: true, clientWidth: 800 };
  const engine = { react: async (...args) => { calls.push(["react", ...args]); }, purge: (...args) => calls.push(["purge", ...args]), relayout: async (...args) => { calls.push(["relayout", ...args]); } };
  const controller = createPlotlyController({ node, loadEngine: () => load ? load(engine) : Promise.resolve(engine), onStatus: (status) => statuses.push(status),
    requestFrame: (callback) => { frames.set(++next, callback); return next; }, cancelFrame: (id) => frames.delete(id),
    observeResize: (callback) => { resize = callback; return () => { disconnected++; }; } });
  const flush = async () => { const work = [...frames.values()]; frames.clear(); work.forEach((callback) => callback()); await settle(); };
  return { controller, engine, calls, statuses, frames, node, flush, resize: () => resize(), disconnected: () => disconnected };
}
const figure = () => { const { descriptor, table } = plotlyFixture(); return buildPlotlyFigure(descriptor, table); };

test("chart controller does not load an engine before a figure is requested", async () => {
  let loads = 0; const h = harness(async (engine) => { loads++; return engine; });
  await h.flush(); assert.equal(loads, 0); h.controller.dispose(); assert.equal(h.disconnected(), 1);
});

test("coalesced draw loads once and copies input before engine mutation", async () => {
  let loads = 0; const h = harness(async (engine) => { loads++; return engine; });
  const first = figure(), second = figure(); second.data[0].y[0] = 5;
  h.engine.react = async (_, data) => { h.calls.push(["react", data]); data[0].y[0] = 99; };
  h.controller.update(first); h.controller.update(second); assert.equal(h.frames.size, 1); await h.flush();
  assert.equal(loads, 1); assert.equal(h.calls.filter(([kind]) => kind === "react").length, 1);
  assert.equal(first.data[0].y[0], 0); assert.equal(second.data[0].y[0], 5); assert.equal(h.statuses.at(-1), "ready"); h.controller.dispose();
});

test("unmount during a lazy import never draws a private result", async () => {
  const gate = deferred(), h = harness(() => gate.promise);
  h.controller.update(figure()); await h.flush(); h.controller.dispose(); gate.resolve(h.engine); await settle();
  assert.equal(h.calls.some(([kind]) => kind === "react"), false); assert.equal(h.statuses.includes("ready"), false); assert.equal(h.disconnected(), 1);
});

test("unmount during an async draw purges immediately and after late completion", async () => {
  const gate = deferred(), h = harness(); h.engine.react = () => gate.promise;
  h.controller.update(figure()); await h.flush(); h.controller.dispose();
  assert.equal(h.calls.filter(([kind]) => kind === "purge").length, 1);
  gate.resolve(); await settle(); assert.equal(h.calls.filter(([kind]) => kind === "purge").length, 2);
  assert.equal(h.statuses.includes("ready"), false); assert.equal(h.frames.size, 0);
});

test("latest queued response replaces an older draw without parallel engine calls", async () => {
  const gate = deferred(), h = harness(); let active = 0, maximum = 0, count = 0;
  h.engine.react = async (_, data) => { active++; maximum = Math.max(maximum, active); h.calls.push(["value", data[0].y[0]]); if (++count === 1) await gate.promise; active--; };
  h.controller.update(figure()); await h.flush();
  const second = figure(), third = figure(); second.data[0].y[0] = 2; third.data[0].y[0] = 3;
  h.controller.update(second); h.controller.update(third); await h.flush(); assert.equal(count, 1);
  gate.resolve(); await settle(); await h.flush();
  assert.deepEqual(h.calls.filter(([kind]) => kind === "value"), [["value", 0], ["value", 3]]); assert.equal(maximum, 1); assert.equal(h.statuses.filter((status) => status === "ready").length, 1); h.controller.dispose();
});

test("resize is coalesced, hidden plots skipped, and all observers/frames released", async () => {
  const h = harness(); h.controller.update(figure()); await h.flush();
  for (let index = 0; index < 20; index++) h.resize(); assert.equal(h.frames.size, 1); await h.flush();
  assert.deepEqual(h.calls.filter(([kind]) => kind === "relayout").map((call) => call[2]), [{ autosize: true }]);
  h.node.clientWidth = 0; h.resize(); await h.flush(); assert.equal(h.calls.filter(([kind]) => kind === "relayout").length, 1);
  h.resize(); h.controller.dispose(); await h.flush(); assert.equal(h.disconnected(), 1); assert.equal(h.frames.size, 0);
});

test("a divider resize during an async draw is applied once after that draw settles", async () => {
  const gate = deferred(), h = harness(); h.engine.react = () => gate.promise;
  h.controller.update(figure()); await h.flush();
  for (let index = 0; index < 20; index++) h.resize(); await h.flush();
  assert.equal(h.calls.some(([kind]) => kind === "relayout"), false);
  gate.resolve(); await settle(); await h.flush();
  assert.deepEqual(h.calls.filter(([kind]) => kind === "relayout").map((call) => call[2]), [{ autosize: true }]); h.controller.dispose();
});

test("fixed controls allow only local zoom, pan and reset; failures stay generic", async () => {
  const h = harness(); h.controller.update(figure()); await h.flush();
  assert.equal(await h.controller.control("sendChartToCloud"), false);
  assert.equal(await h.controller.control("pan"), true); assert.equal(await h.controller.control("reset"), true);
  assert.deepEqual(h.calls.filter(([kind]) => kind === "relayout").map((call) => call[2]), [{ dragmode: "pan" }, { "xaxis.autorange": true, "yaxis.autorange": true, dragmode: "zoom" }]);
  h.engine.relayout = () => { throw new Error("PRIVATE SQL https://secret.invalid"); };
  assert.equal(await h.controller.control("zoom"), false); assert.equal(h.statuses.at(-1), "error"); assert.equal(JSON.stringify(h.statuses).includes("PRIVATE"), false); h.controller.dispose();
});

test("an acknowledged pan mode remains truthful when a follow-up draw waits behind that control", async () => {
  const h = harness(), gate = deferred(), modes = [];
  h.engine.react = async (_, data, layout) => { modes.push(layout.dragmode); };
  h.controller.update(figure()); await h.flush();
  h.engine.relayout = () => gate.promise;
  const pan = h.controller.control("pan"); h.controller.update(figure()); await h.flush();
  gate.resolve(); assert.equal(await pan, true); await h.flush();
  assert.deepEqual(modes, ["zoom", "pan"]); h.controller.dispose();
});

test("reset requested during a resize is acknowledged after the resize rather than dropped", async () => {
  const h = harness(), gate = deferred(), fields = [];
  h.controller.update(figure()); await h.flush();
  h.engine.relayout = async (_, next) => { fields.push(next); if (fields.length === 1) await gate.promise; };
  h.resize(); await h.flush(); let acknowledged = false;
  const reset = h.controller.control("reset").then((value) => { acknowledged = true; return value; });
  await settle(); assert.equal(acknowledged, false);
  gate.resolve(); await settle(); await h.flush(); assert.equal(await reset, true);
  assert.deepEqual(fields, [{ autosize: true }, { "xaxis.autorange": true, "yaxis.autorange": true, dragmode: "zoom" }]); h.controller.dispose();
});

test("a busy chart retains only the latest known control and disposes any pending acknowledgement", async () => {
  const h = harness(), gate = deferred(), fields = [];
  h.controller.update(figure()); await h.flush();
  h.engine.relayout = async (_, next) => { fields.push(next); if (fields.length === 1) await gate.promise; };
  h.resize(); await h.flush();
  const pan = h.controller.control("pan"), zoom = h.controller.control("zoom"), reset = h.controller.control("reset");
  assert.equal(await pan, false); assert.equal(await zoom, false); assert.equal(await h.controller.control("sendChartToCloud"), false);
  gate.resolve(); await settle(); await h.flush(); assert.equal(await reset, true); assert.equal(fields.length, 2);
  const draw = deferred(); h.engine.react = () => draw.promise; h.controller.update(figure()); await h.flush();
  const pending = h.controller.control("pan"); h.controller.dispose(); assert.equal(await pending, false); draw.resolve(); await settle();
});
