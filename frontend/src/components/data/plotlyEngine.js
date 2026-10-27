// Keep the browser-only engine behind an explicit chart mount. This package is
// Plotly's dependency-free basic bundle: bar, pie and SVG scatter only.
let pending;
export function loadPlotlyEngine() {
  if (!pending) pending = import("plotly.js-basic-dist-min").then((module) => {
    const engine = module.default || module;
    if (typeof engine.react !== "function" || typeof engine.purge !== "function" || typeof engine.relayout !== "function") {
      throw new Error("chart_engine_unavailable");
    }
    return engine;
  }).catch(() => { pending = undefined; throw new Error("chart_engine_unavailable"); });
  return pending;
}
