import React from "react";
import { analysisLabel, analysisConnectionLabel } from "../../services/analysisPresentation.js";
import { terminalAnalysis } from "../../services/workspaceContract.js";

export default function AnalysisStatus({ request, connection, onReconnect }) {
  if (!request) return null;
  const terminal = terminalAnalysis(request.state), detail = terminal ? "" : analysisConnectionLabel(connection);
  return <div className="analysis-status" data-analysis-state={request.state} data-analysis-stage={request.stage}>
    <div role="status" aria-live="polite" aria-atomic="true"><strong>{analysisLabel(request)}</strong>{detail && <p>{detail}</p>}</div>
    {!terminal && <button type="button" onClick={onReconnect}>Check saved status</button>}
  </div>;
}
