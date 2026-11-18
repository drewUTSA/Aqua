import { noteLimits } from "../src/features/contextNotes/contract.js";

export const ownerId = "10000000-0000-4000-8000-000000000001", noteId = "20000000-0000-4000-8000-000000000002";
export const otherId = "30000000-0000-4000-8000-000000000003", requestId = "40000000-0000-4000-8000-000000000004";
export const scope = { id: "a".repeat(64), can_use: true };
export const fields = () => ({ kind: "metric_definition", label: "My team definition", body: "For our team, a completed task means reviewed.\nCheck the report definition separately." });
export const note = () => ({ id: noteId, revision: 2, ...fields(), created_at: "2026-11-17T10:00:00+00:00", updated_at: "2026-11-17T10:10:00+00:00" });
export function item() { const { body, ...value } = note(); return { ...value, availability: "available" }; }
export const unavailable = () => ({ id: otherId, revision: 4, availability: "unavailable", label: "Unavailable saved context", kind: null, created_at: null, updated_at: null });
export const envelope = extra => ({ schemaVersion: 1, owner_id: ownerId, scope: { ...scope }, unverified: true, execution_enabled: false, ...extra });
export const library = () => envelope({ items: [item(), unavailable()], limits: { ...noteLimits } });
export const readReply = () => envelope({ note: note() });
export const prepared = () => envelope({ source: { id: noteId, revision: 2, kind: fields().kind, label: fields().label }, draft: fields().body, requires_review: true });
