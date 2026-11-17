import { workspaceRequest, WorkspaceError } from "../../services/workspaceClient.js";
import { decodeBankContext, decodeBankReport } from "./contract.js";

export async function bankDemoContext({ ownerId, ...options } = {}) {
  const value = await workspaceRequest("/bank-demo/context", { ...options, method: "GET", body: undefined, timeout: 5000, maxBytes: 32768 });
  return decodeBankContext(value, ownerId);
}
export async function bankDemoReport(reportId, context, { ownerId, ...options } = {}) {
  if (context?.ownerId !== ownerId || !context?.reports?.some(report => report.id === reportId) || typeof context.sourceRevision !== "string"
    || !/^[a-f0-9]{64}$/.test(context.sourceRevision)) throw new WorkspaceError("invalid_input");
  const body = { schemaVersion: 1, report_id: reportId, expected_source_revision: context.sourceRevision };
  const value = await workspaceRequest("/bank-demo/reports", { ...options, method: "POST", body, timeout: 5000, maxBytes: 32768, expectedStatuses: [200] });
  return decodeBankReport(value, ownerId, reportId, context);
}
