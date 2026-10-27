import { randomUUID } from "node:crypto";
import { analysisFixture } from "./p07-browser-fixture.mjs";

// Disposable intercepted contract fixture. Production authorization is tested
// independently against actual FastAPI/PostgreSQL, never inferred from this UI double.
export function workspaceFixture(fixture) {
  const analysis = analysisFixture(fixture);
  const owners = new Map();
  const owner = () => { if (!owners.has(fixture.email)) owners.set(fixture.email, { chats: new Map(), projects: new Map(), prompts: new Map(), operations: new Map() }); return owners.get(fixture.email); };
  const now = () => new Date().toISOString();
  return async function route(call, reply) {
    const { url, method, body, headers } = call, path = url.pathname;
    if (!/^\/api\/v1\/(chats|projects|me\/saved-prompts|starter-prompts|analysis-requests)(\/|$)/.test(path)) return false;
    if (!fixture.email) { await reply(401, {}); return true; }
    if (method !== "GET" && headers["x-csrf-token"] !== "fixture-session-csrf") { await reply(403, {}); return true; }
    const data = owner(), json = async (status, value) => { await reply(status, value); return true; };
    if (path.startsWith("/api/v1/analysis-requests/")) return analysis.route(call, reply);
    if (path === "/api/v1/starter-prompts") return json(200, { items: [
      { id: "loans", title: "Loans currently in debt", prompt: "How many loans are currently in debt?" },
      { id: "districts", title: "Compare districts", prompt: "Which 5 districts have the highest average salary?" },
      { id: "accounts", title: "Account growth", prompt: "How many accounts were opened each year?" } ] });
    if (path === "/api/v1/chats/search" && method === "POST") {
      const items = [...data.chats.values()].map((item) => item.chat).filter((item) => item.archived === Boolean(body.archived)
        && item.title.toLowerCase().startsWith(body.search.toLowerCase()) && (!body.project_id || item.project_id === body.project_id))
        .sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at) || b.id.localeCompare(a.id));
      return json(200, { items: items.slice(0, 20), next_cursor: null });
    }
    const chatMatch = /^\/api\/v1\/chats(?:\/([^/]+))?(?:\/messages(?:\/([^/]+)\/retries)?)?$/.exec(path);
    if (chatMatch) {
      const id = chatMatch[1], inputId = chatMatch[2], existing = id && data.chats.get(id);
      if (id && !existing) return json(404, {});
      if (method === "GET") {
        if (path.endsWith("/messages")) {
          const snapshot = structuredClone({ items: existing.messages.map((message) => fixture.canQuery || message.role === "user" ? message
            : { ...message, response: null, content: "", result_unavailable: true }), older_cursor: null });
          if (fixture.holdHistory) { fixture.held.push({ kind: "history", finish: () => reply(200, snapshot) }); return true; }
          return json(200, snapshot);
        }
        if (id) return json(200, { chat: existing.chat });
        let items = [...data.chats.values()].map((item) => item.chat).filter((item) => item.archived === (url.searchParams.get("archived") === "true"));
        const search = (url.searchParams.get("search") || "").toLowerCase(), project = url.searchParams.get("project_id");
        items = items.filter((item) => item.title.toLowerCase().startsWith(search) && (!project || item.project_id === project)).sort((a, b) => b.last_activity_at.localeCompare(a.last_activity_at) || b.id.localeCompare(a.id));
        return json(200, { items: items.slice(0, 20), next_cursor: null });
      }
      if (method === "PATCH") { if (body.revision !== existing.chat.revision) return json(409, {});
        Object.assign(existing.chat, Object.fromEntries(Object.entries(body).filter(([key]) => ["title", "archived", "project_id"].includes(key)))); existing.chat.revision++;
        return json(200, { chat: existing.chat }); }
      if (method === "DELETE") { if (Number(url.searchParams.get("revision")) !== existing.chat.revision) return json(409, {}); data.chats.delete(id); return json(204); }
      if (!fixture.canQuery) return json(403, {});
      const prior = data.operations.get(body.client_request_id);
      if (prior) return json(data.chats.has(prior.chat.id) ? 200 : 404, data.chats.has(prior.chat.id) ? prior : {});
      if (fixture.nextError?.path === "/api/query") { const status = fixture.nextError.status; fixture.nextError = null; return json(status, {}); }
      const record = existing || { chat: { id: randomUUID(), title: body.question.replace(/\s+/g, " ").slice(0, 120), project_id: body.project_id || null,
        archived: false, revision: 1, message_count: 0, last_activity_at: now(), created_at: now() }, messages: [] };
      const requestId = randomUUID(), input = inputId ? record.messages.find((item) => item.id === inputId) : { id: randomUUID(), chat_id: record.chat.id,
        sequence: record.messages.length + 1, role: "user", content: body.question, request_id: requestId, reply_to: null, model_id: body.model || "fixture-model", status: "complete", response: null, result_unavailable: false, created_at: now() };
      if (!input) return json(404, {}); if (!inputId) record.messages.push(input);
      if (input.content?.startsWith("P07 ")) return json(202, analysis.submit(data, record, input, body, requestId));
      const captured = fixture.queryMessage;
      const finish = async () => {
        const response = { status: "success", message: captured, sql: "SELECT 1 AS synthetic_value", model: "fixture-model", tables: [], visualizations: [], kpis: [] };
        const assistant = { ...input, id: randomUUID(), sequence: record.messages.length + 1, role: "aqua", content: "", request_id: requestId, reply_to: input.id, response };
        record.messages.push(assistant); record.chat.message_count = record.messages.length; record.chat.revision++; record.chat.last_activity_at = now();
        data.chats.set(record.chat.id, record);
        const result = { chat: record.chat, request: { id: requestId, client_request_id: body.client_request_id, state: "complete", input_message_id: input.id, reply_message_id: assistant.id }, input_message: input, assistant_message: assistant, response };
        data.operations.set(body.client_request_id, result);
        // Hold only the transport: canonical rows already exist server-side.
        if (fixture.holdQuery) fixture.held.push({ kind: "query", finish: () => reply(existing ? 200 : 201, result) });
        else await reply(existing ? 200 : 201, result);
      };
      await finish(); return true;
    }
    const match = /^\/api\/v1\/(projects|me\/saved-prompts)(?:\/([^/]+))?(\/uses)?$/.exec(path);
    if (!match) return json(404, {});
    const projects = match[1] === "projects", collection = projects ? data.projects : data.prompts, item = match[2] && collection.get(match[2]), key = projects ? "project" : "saved_prompt";
    if (match[2] && !item) return json(404, {});
    if (method === "GET") return json(200, { items: [...collection.values()], next_cursor: null });
    if (method === "DELETE") { collection.delete(item.id); if (projects) for (const value of data.chats.values()) if (value.chat.project_id === item.id) { value.chat.project_id = null; value.chat.revision++; } return json(204); }
    if (match[3]) { item.use_count++; return json(200, { saved_prompt: item }); }
    if (method === "PATCH") { if (body.revision !== item.revision) return json(409, {}); Object.assign(item, body); item.revision++; return json(200, { [key]: item }); }
    const created = { id: randomUUID(), revision: 1, created_at: now(), updated_at: now(), ...(projects ? { name: body.name, archived: false }
      : { label: body.label, prompt: body.prompt, pinned: body.pinned || false, use_count: 0, last_used_at: null }) };
    collection.set(created.id, created); return json(201, { [key]: created });
  };
}
