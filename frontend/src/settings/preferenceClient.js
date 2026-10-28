import { workspaceRequest } from "../services/workspaceClient.js";
import { preferenceResponse, validateValues } from "./schema.js";

export async function readPreferences(options = {}) {
  return preferenceResponse(await workspaceRequest("/me/preferences", options));
}
export async function writePreferences(snapshot, options = {}) {
  validateValues(snapshot.account, "account");
  return preferenceResponse(await workspaceRequest("/me/preferences", { ...options, method: "PUT", body: {
    schemaVersion: 1, expectedRevision: snapshot.revision, values: snapshot.account
  } }));
}
