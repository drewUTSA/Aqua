import { randomUUID } from "node:crypto";
const terminal = (state) => ["complete", "error", "cancelled", "interrupted", "expired"].includes(state);

// Only this disposable synthetic fixture writes real HTTP event-stream chunks.
// The production API/DB journeys use the separate isolated backend bridge.
export function analysisFixture(fixture) {
  const requests = new Map(), subscribers = new Set();
  fixture.analysisRequests = requests; fixture.analysisStreamFrames = 0;
  fixture.analysisChange = (id, state, stage = state) => {
    const item = requests.get(id); if (!item || terminal(item.result.request.state)) return;
    const { result } = item; Object.assign(result.request, { state, stage, version: result.request.version + 1,
      last_event_sequence: result.request.last_event_sequence + 1, cancel_requested: ["cancelling", "cancelled"].includes(state), cancellable: !terminal(state) && state !== "cancelling" });
    result.assistant_message.status = terminal(state) ? state : "pending";
    if (state === "complete") result.assistant_message.response = result.response = { status: "success", message: "P07 synthetic completed answer", sql: "SELECT 7 AS synthetic_value",
      model: "fixture-model", tables: [], visualizations: [], kpis: [] };
    if (state === "complete" && result.input_message.content === "P07 synthetic exact precision") {
      result.response.tables = [{ id: "result", title: "Exact fixture values", columns: [{ key: "amount", label: "Amount", type: "number" }], rows: [{ amount: 9007199254740992 }, { amount: -0.12345678901234568 }] }];
      result.response.visualizations = [{ id: "rounded-chart" }]; result.response.kpis = [{ id: "rounded-metric", value: 9007199254740992 }];
      result.response.result_metadata = { version: 1, source: { id: "a".repeat(64), freshness_at: null }, generated_at: new Date().toISOString(), filters: null, truncated: true,
        max_rows: 1000, aggregation: "unknown", column_units: { amount: null }, exact_values: [
          { row: 0, column: "amount", value: "9007199254740993", kind: "integer" }, { row: 1, column: "amount", value: "-0.1234567890123456789", kind: "decimal" }] };
    }
    for (const stream of item.streams) stream();
  };
  fixture.streamAnalysis = (request, response) => {
    const match = /^\/api\/v1\/analysis-requests\/([0-9a-f-]{36})\/events$/.exec(new URL(request.url, "http://127.0.0.1").pathname);
    const item = match && requests.get(match[1]);
    if (!item || fixture.email !== item.owner || !fixture.canQuery || !item.data.chats.has(item.result.chat.id)) { response.writeHead(404); response.end(); return; }
    if (subscribers.size >= 4 || fixture.analysisPollingOnly) { response.writeHead(503); response.end(); return; }
    response.writeHead(200, { "Content-Type": "text/event-stream", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" }); response.flushHeaders();
    let frames = 0;
    const send = () => {
      if (response.destroyed || response.writableEnded || frames++ >= 32) return;
      if (fixture.email !== item.owner || !fixture.canQuery || !item.data.chats.has(item.result.chat.id)) { response.end(); return; }
      const value = item.result.request, sequence = value.last_event_sequence;
      const encoded = `event: progress\nid: ${value.id}:${sequence}\ndata: ${JSON.stringify({ request_id: value.id, sequence, version: value.version, state: value.state, stage: value.stage })}\n\n`;
      response.write(encoded); fixture.analysisStreamFrames++;
      if (terminal(value.state)) response.end();
    };
    item.streams.add(send); subscribers.add(response); const timer = setTimeout(() => response.end(), 60000);
    response.on("close", () => { clearTimeout(timer); item.streams.delete(send); subscribers.delete(response); });
    send();
  };
  fixture.closeAnalysisStreams = () => { for (const response of subscribers) response.end(); };
  return {
    submit(data, record, input, body, id) {
      const assistant = { ...input, id: randomUUID(), request_id: id, sequence: record.messages.length + 1, role: "aqua", reply_to: input.id, content: "", status: "pending", response: null };
      record.messages.push(assistant); record.chat.message_count = record.messages.length; record.chat.revision++; data.chats.set(record.chat.id, record);
      const result = { chat: record.chat, request: { id, client_request_id: body.client_request_id, state: "queued", stage: "queued", version: 1, last_event_sequence: 0,
        deadline_at: new Date(Date.now() + 180000).toISOString(), cancel_requested: false, cancellable: true, input_message_id: input.id, reply_message_id: assistant.id }, input_message: input, assistant_message: assistant, response: null };
      data.operations.set(body.client_request_id, result); requests.set(id, { owner: fixture.email, data, result, streams: new Set() }); return result;
    },
    async route({ url, method, body }, reply) {
      const match = /^\/api\/v1\/analysis-requests\/([^/]+)(\/cancel)?$/.exec(url.pathname); if (!match) return false;
      const item = requests.get(match[1]);
      if (!item || item.owner !== fixture.email || !item.data.chats.has(item.result.chat.id)) { await reply(404, {}); return true; }
      if (!fixture.canQuery) { await reply(403, {}); return true; }
      if (match[2] && method === "POST" && body && Object.keys(body).length === 0) {
        if (fixture.analysisCancelFailure) { await reply(503, {}); return true; }
        fixture.analysisChange(match[1], "cancelling"); await reply(202, structuredClone(item.result)); return true;
      }
      if (!match[2] && method === "GET") {
        const result = structuredClone(item.result);
        if (fixture.holdAnalysisStatus) fixture.held.push({ kind: "analysis-status", finish: () => reply(200, result) }); else await reply(200, result);
        return true;
      }
      await reply(405, {}); return true;
    }
  };
}
