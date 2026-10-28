import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { buildPlotlyFigure } from "../../services/plotlyFigure.js";
import { createPlotlyController } from "./plotlyController.js";
import { loadPlotlyEngine } from "./plotlyEngine.js";
import { useReducedMotion } from "../../hooks/useReducedMotion.js";
import "./PlotlyChart.css";

export default function PlotlyChart({ descriptor, table, theme = "opal", preferences, devicePreferences, revisionKey, onTableView }) {
  const node = useRef(null), controller = useRef(null), description = useId();
  const [status, setStatus] = useState("loading"), [mode, setMode] = useState("zoom");
  const [controlBusy, setControlBusy] = useState(false);
  const reduced = useReducedMotion();
  const animate = !!devicePreferences && devicePreferences.chart_motion === "system" && devicePreferences.motion !== "reduce" && !reduced;
  const textScale = devicePreferences?.text_scale;
  const figure = useMemo(() => buildPlotlyFigure(descriptor, table, { theme, preferences, revisionKey, animate, textScale }), [descriptor, table, theme, preferences, revisionKey, animate, textScale]);
  useEffect(() => {
    if (!figure || !node.current) return;
    const owner = createPlotlyController({ node: node.current, loadEngine: loadPlotlyEngine, onStatus: setStatus });
    controller.current = owner; setControlBusy(false);
    return () => { owner.dispose(); if (controller.current === owner) controller.current = null; };
  }, [Boolean(figure)]);
  useEffect(() => { if (figure) controller.current?.update(figure); }, [figure]);
  const control = async (action) => {
    const owner = controller.current; if (!owner || controlBusy) return;
    setControlBusy(true);
    try { if (await owner.control(action)) setMode(action === "reset" ? "zoom" : action); }
    finally { if (controller.current === owner) setControlBusy(false); }
  };
  const unavailable = !figure || status === "error";
  return (
    <section className="plotly-chart" aria-label={descriptor?.title || "Result chart"} data-chart-status={unavailable ? "unavailable" : status}>
      <p className="plotly-chart__description" id={description}>
        {unavailable ? "Chart unavailable. The result table contains the accessible data."
          : preferences?.expanded_summaries === false ? "Chart overview. The result table provides every value and the text alternative."
            : "Chart overview. Use the result table for every value, sorting and export. Long labels are shortened; hover and the table keep the full text. Drag to zoom; controls choose zoom, pan or reset."}
      </p>
      {!unavailable && <div className="plotly-chart__controls" role="group" aria-label="Chart controls">
        <button type="button" aria-pressed={mode === "zoom"} disabled={status !== "ready" || controlBusy} onClick={() => void control("zoom")}>Zoom</button>
        <button type="button" aria-pressed={mode === "pan"} disabled={status !== "ready" || controlBusy} onClick={() => void control("pan")}>Pan</button>
        <button type="button" disabled={status !== "ready" || controlBusy} onClick={() => void control("reset")}>Reset chart</button>
      </div>}
      {onTableView && <button type="button" className="text-action" onClick={onTableView}>View result table</button>}
      {figure && <div className="plotly-chart__canvas" hidden={unavailable} ref={node} role="img" aria-label={`${descriptor.title}. ${table.rows.length} rows.`} aria-describedby={description} />}
      {status === "loading" && figure && <p className="plotly-chart__status" role="status">Preparing chart…</p>}
      {unavailable && <p className="plotly-chart__status" role="status">Chart unavailable. Table and export remain available.</p>}
    </section>
  );
}
