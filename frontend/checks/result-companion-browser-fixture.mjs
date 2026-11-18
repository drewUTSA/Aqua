// Opt-in browser double: fixed synthetic saved rows, never a backend/auth proof.
import { resultFixture } from "./result-companion-fixture.mjs";
import { createHash } from "node:crypto";

export const RESULT_CHAT_TITLES = Object.freeze(["Saved result sample A", "Saved result sample B"]);
const ids = ["41000000-0000-4000-8000-000000000001", "41000000-0000-4000-8000-000000000002"];
const requests = ["42000000-0000-4000-8000-000000000001", "42000000-0000-4000-8000-000000000002"];
const inputs = ["43000000-0000-4000-8000-000000000001", "43000000-0000-4000-8000-000000000002"];
const messages = ["44000000-0000-4000-8000-000000000001", "44000000-0000-4000-8000-000000000002"];
const sample = resultFixture(), when = "2026-11-17T18:00:00Z";
const response = { ...sample.raw, result_metadata: sample.metadata };
const chats = ids.map((id, index) => ({ id, title: RESULT_CHAT_TITLES[index], project_id: null, archived: false,
  revision: 1, message_count: 2, created_at: when, last_activity_at: when }));
export const RESULT_BROWSER_GOLD = Object.freeze({ minimum: "-0.0000000001", maximum: "9007199254740993.01", rows: 4, missing: 1, minimum_ties: 2 });
export const RESULT_BROWSER_FIXTURE_SHA256 = createHash("sha256").update(JSON.stringify({ chats, response, reply: sample.reply })).digest("hex");
const error = (reply, status) => reply(status, { error: { code: status === 404 ? "not_found" : status === 403 ? "access_denied" : "invalid_request" } });
function history(index, allowed) {
  const common = { chat_id: ids[index], request_id: requests[index], model_id: "fixture-model", status: "complete", created_at: when };
  return [{ ...common, id: inputs[index], sequence: 1, role: "user", content: sample.reply.brief.question, reply_to: null, response: null, result_unavailable: false },
    { ...common, id: messages[index], sequence: 2, role: "aqua", content: "", reply_to: inputs[index],
      response: allowed ? structuredClone(response) : null, result_unavailable: !allowed }];
}
function projection(index, column, owner) {
  const answer = structuredClone(sample.reply);
  Object.assign(answer, { owner_id: owner, chat_id: ids[index], request_id: requests[index], assistant_message_id: messages[index], job_version: 7 });
  if (column === 1) {
    answer.brief.field = { index: 1, key: "tag", label: "Tag", kind: "text", unit: null };
    answer.brief.counts = { returned_rows: 4, missing_values: 0, non_missing_values: 4 }; answer.brief.numeric = null;
    answer.brief.checks = answer.brief.checks.filter(item => item.id !== "missing_values"); answer.brief.followup_intents = ["verify_scope"];
  }
  return answer;
}

export function installResultCompanionFixture(base) {
  const original = base.route.bind(base);
  const state = { enabled: true, hold: false, failNext: null, blockChunk: false, historyRevision: null,
    pending: [], calls: [], peakHeld: 0, geometry: null,
    async release() { for (const finish of this.pending.splice(0)) await finish(); } };
  base.route = async (request, reply) => {
    const url = new URL(request.url), brief = url.pathname === "/api/v1/companion/result-brief";
    const chatIndex = ids.findIndex(id => url.pathname === `/api/v1/chats/${id}` || url.pathname === `/api/v1/chats/${id}/messages`);
    const saved = request.method === "GET" && (url.pathname === "/api/v1/chats" || chatIndex >= 0);
    if (!brief && !saved) return original(request, reply);
    if (!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(url.origin) || url.username || url.password) return error(reply, 403);
    if (!base.email) return error(reply, 401);
    if (saved) {
      if (url.pathname === "/api/v1/chats") return reply(200, { items: structuredClone(chats), next_cursor: null });
      return reply(200, url.pathname.endsWith("/messages") ? { items: history(chatIndex, base.canQuery), older_cursor: null } : { chat: structuredClone(chats[chatIndex]) });
    }
    if (state.calls.length >= 80) return error(reply, 429);
    state.calls.push({ method: request.method, path: url.pathname });
    if (!state.enabled) return error(reply, 404);
    if (!base.canQuery) return error(reply, 403);
    if (request.method !== "POST" || url.search || url.hash) return error(reply, 422);
    const headers = Object.fromEntries(Object.entries(request.headers || {}).map(([name, value]) => [name.toLowerCase(), value]));
    if (headers.origin !== url.origin || headers["x-csrf-token"] !== "fixture-session-csrf") return error(reply, 403);
    let body;
    try { if (Buffer.byteLength(request.postData || "") > 8192) return error(reply, 413); body = JSON.parse(request.postData); }
    catch { return error(reply, 422); }
    if (!body || Array.isArray(body) || Object.keys(body).sort().join() !== "column_index,request_id,schemaVersion" || body.schemaVersion !== 1
      || !Number.isSafeInteger(body.column_index) || body.column_index < 0 || body.column_index > 1) return error(reply, 422);
    const index = requests.indexOf(body.request_id); if (index < 0) return error(reply, 404);
    if (state.failNext !== null) { const status = state.failNext; state.failNext = null;
      if (![403, 409, 503].includes(status)) throw Error("result_fixture_failure_invalid"); return error(reply, status); }
    const answer = projection(index, body.column_index, base.session().user.id);
    if (Buffer.byteLength(JSON.stringify(answer)) > 32768) throw Error("result_fixture_reply_oversized");
    const finish = () => reply(200, answer, state.historyRevision ? { "X-Aqua-History-Revision": state.historyRevision } : {});
    if (state.hold) {
      if (state.pending.length >= 4) return error(reply, 429);
      state.pending.push(finish); state.peakHeld = Math.max(state.peakHeld, state.pending.length); return;
    }
    return finish();
  };
  return state;
}
