// One engine operation at a time, one pending figure, and one resize frame.
// Disposal fences both an unresolved lazy import and an already-running draw.
export function createPlotlyController({ node, loadEngine, onStatus = () => {},
  requestFrame = requestAnimationFrame, cancelFrame = cancelAnimationFrame,
  observeResize = (callback) => { const observer = new ResizeObserver(callback); observer.observe(node); return () => observer.disconnect(); }
}) {
  let engine, pending, controlTask, busy = false, disposed = false, drawFrame, resizeFrame, resizeNeeded = false, revision = 0, mode = "zoom";
  const purge = () => { if (engine) { try { engine.purge(node); } catch { /* Detached plots still release their owner. */ } } };
  const schedule = () => {
    if (!disposed && !busy && (pending || controlTask) && drawFrame === undefined) drawFrame = requestFrame(() => {
      drawFrame = undefined; if (pending) void draw(); else void runControl();
    });
  };
  async function draw() {
    if (disposed || busy || !pending) return;
    const figure = pending, current = revision; pending = undefined; busy = true;
    try {
      engine ||= await loadEngine();
      if (disposed) return;
      // Plotly mutates its inputs. Never hand it the response table, descriptor,
      // or an object that a future figure update could share.
      const copy = structuredClone(figure);
      copy.layout.dragmode = mode;
      await engine.react(node, copy.data, copy.layout, copy.config);
      if (!disposed && current === revision) onStatus("ready");
    } catch {
      if (!disposed && current === revision) { purge(); onStatus("error"); }
    } finally {
      busy = false;
      if (disposed) purge(); else { schedule(); scheduleResize(); }
    }
  }
  function scheduleResize() {
    if (disposed || busy || pending || controlTask || !resizeNeeded || resizeFrame !== undefined) return;
    resizeFrame = requestFrame(() => {
      resizeFrame = undefined;
      if (disposed || busy || !engine || !node.isConnected || node.clientWidth <= 0) return;
      resizeNeeded = false;
      // Fixed app-owned layout fields only; no event payload enters relayout.
      void relayout({ autosize: true });
    });
  }
  const stopResize = observeResize(() => { resizeNeeded = true; scheduleResize(); });
  async function relayout(fields) {
    if (disposed || busy || !engine) return false;
    busy = true;
    try { await engine.relayout(node, fields); return !disposed; }
    catch { if (!disposed) { purge(); onStatus("error"); } return false; }
    finally { busy = false; if (disposed) purge(); else { schedule(); scheduleResize(); } }
  }
  async function runControl() {
    if (disposed || busy || !engine || !controlTask) return;
    const task = controlTask; controlTask = undefined;
    const changed = await relayout(task.action === "reset" ? { "xaxis.autorange": true, "yaxis.autorange": true, dragmode: "zoom" }
      : { dragmode: task.action });
    if (changed) mode = task.action === "reset" ? "zoom" : task.action;
    task.resolve(changed);
  }
  return {
    update(figure) {
      if (disposed) return;
      revision += 1; pending = figure; onStatus("loading"); schedule();
    },
    control(action) {
      if (disposed || !engine || !["zoom", "pan", "reset"].includes(action)) return Promise.resolve(false);
      return new Promise((resolve) => {
        // One pending local action, with explicit false acknowledgements for
        // superseded actions. Never replay unknown data or grow a click queue.
        controlTask?.resolve(false); controlTask = { action, resolve };
        if (!busy && !pending) void runControl(); else schedule();
      });
    },
    dispose() {
      if (disposed) return;
      disposed = true; revision += 1; pending = undefined;
      controlTask?.resolve(false); controlTask = undefined;
      if (drawFrame !== undefined) cancelFrame(drawFrame);
      if (resizeFrame !== undefined) cancelFrame(resizeFrame);
      stopResize(); purge();
    }
  };
}
