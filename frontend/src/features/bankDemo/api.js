import { workspaceRequest, WorkspaceError } from "../../services/workspaceClient.js";
import { decodeBankContext, decodeCalculation, decodeRequestedReport, validReportRequirements } from "./contract.js";

export async function bankDemoContext({ ownerId, ...options } = {}) {
  const value = await workspaceRequest("/bank-demo/context", { ...options, method: "GET", body: undefined, timeout: 5000, maxBytes: 32768 });
  return decodeBankContext(value, ownerId);
}
export async function bankDemoCalculation(draft, context, options) {
  const { confirmedInputs, rowLabels, reportTitle, ...body } = draft;
  const response = await workspaceRequest("/bank-demo/calculations", { ...options, method: "POST", body, timeout: 5000, maxBytes: 32768, expectedStatuses: [200] });
  return decodeCalculation(response, options.ownerId, context, draft);
}
export async function bankDemoReport(reportId, context, { ownerId, requirements, ...options } = {}) {
  if (context?.ownerId !== ownerId || !context?.reports?.some(report => report.id === reportId) || typeof context.sourceRevision !== "string"
    || !/^[a-f0-9]{64}$/.test(context.sourceRevision)) throw new WorkspaceError("invalid_input");
  const body = { schemaVersion: 1, report_id: reportId, expected_source_revision: context.sourceRevision };
  if (requirements !== undefined) {
    if (!validReportRequirements(requirements)) throw new WorkspaceError("invalid_input");
    body.requirements = { ...requirements };
  }
  const value = await workspaceRequest("/bank-demo/reports", { ...options, method: "POST", body, timeout: 5000, maxBytes: 32768, expectedStatuses: [200] });
  return decodeRequestedReport(value, ownerId, reportId, context, body.requirements);
}
