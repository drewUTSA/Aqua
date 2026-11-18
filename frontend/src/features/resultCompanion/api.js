import { workspaceRequest, WorkspaceError } from "../../services/workspaceClient.js";
import { decodeResultBrief } from "./contract.js";

export async function readResultBrief(binding, columnIndex, options = {}) {
  if (!binding || options.ownerId !== binding.ownerId || !Number.isSafeInteger(columnIndex) || columnIndex < 0 || columnIndex >= binding.table.columns.length) throw new WorkspaceError("invalid_input");
  const body = { schemaVersion: 1, request_id: binding.requestId, column_index: columnIndex };
  const value = await workspaceRequest("/companion/result-brief", { ...options, method: "POST", body, timeout: 5000, maxBytes: 32768, expectedStatuses: [200] });
  return decodeResultBrief(value, binding, columnIndex);
}
