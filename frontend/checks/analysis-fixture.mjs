export const CHAT = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", INPUT = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  REPLY = "cccccccc-cccc-4ccc-8ccc-cccccccccccc", REQUEST = "dddddddd-dddd-4ddd-8ddd-dddddddddddd";
export function snapshot(state = "running", stage = "generating", version = 2, sequence = 1) {
  const complete = ["complete", "error", "cancelled", "interrupted", "expired"].includes(state);
  const chat = { id: CHAT, title: "Owned fixture question", project_id: null, archived: false, revision: 1, message_count: 2, last_activity_at: "2026-10-26T12:00:00Z" };
  const input = { id: INPUT, chat_id: CHAT, sequence: 1, role: "user", content: "Owned fixture question", request_id: REQUEST, reply_to: null,
    model_id: "gemini", status: "complete", response: null, result_unavailable: false };
  const response = state === "complete" ? { status: "success", message: "PRIVATE_RESULT", sql: "SELECT PRIVATE_SQL", tables: [], visualizations: [], kpis: [] } : null;
  return { chat, request: { id: REQUEST, client_request_id: REQUEST, input_message_id: INPUT, reply_message_id: REPLY, state, stage, version,
    last_event_sequence: sequence, deadline_at: "2099-01-01T00:00:00Z", cancel_requested: state === "cancelling", cancellable: !complete && state !== "cancelling" },
    input_message: input, assistant_message: { ...input, id: REPLY, role: "aqua", sequence: 2, reply_to: INPUT, status: complete ? state : "pending", response }, response };
}
export const event = (state = "running", stage = "generating", version = 2, sequence = 1) => ({ request_id: REQUEST, state, stage, version, sequence });
export const frame = (value = event(), type = "progress") => `event: ${type}\nid: ${value.request_id}:${value.sequence}\ndata: ${JSON.stringify(value)}\n\n`;
export const json = (body, status = 200) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
