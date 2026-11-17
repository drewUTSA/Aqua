// Original fictional HTTP projections only. This is a browser API double, not
// backend authorization, PostgreSQL, MCP transport or a bank connection proof.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { decodeBankContext, decodeBankReport } from "../src/features/bankDemo/contract.js";

const raw = readFileSync(new URL("./bank-demo-browser-data.json", import.meta.url));
assert.equal(createHash("sha256").update(raw).digest("hex"), "47bb678ace09af350d576ea218927edc26dc15cebbcd160e31d53bd93894da47");
assert.ok(raw.length < 20000);
const data = JSON.parse(raw);
export const BANK_FIXTURE_SHA256 = createHash("sha256").update(raw).digest("hex");
export const BANK_REPORT_ID = "deposit_portfolio_summary";
export const BANK_CHAT_TITLES = ["Synthetic saved context A", "Synthetic saved context B"];
const personas = ["none", "teller", "analyst", "manager"];
for (const persona of personas) decodeBankContext(data.contexts[persona], data.contexts[persona].owner_id);
for (const report of data.reports) decodeBankReport(report, report.owner_id, report.result.reportId,
  decodeBankContext(data.contexts.manager, report.owner_id));
export const bankReportGold = () => structuredClone(data.reports.find(item => item.result.reportId === BANK_REPORT_ID).result);

const chatIds = ["44000000-0000-4000-8000-000000000001", "44000000-0000-4000-8000-000000000002"];
const chats = chatIds.map((id, index) => ({ id, title: BANK_CHAT_TITLES[index], project_id: null, archived: false,
  revision: 1, message_count: 1, created_at: "2026-11-16T00:00:00Z", last_activity_at: "2026-11-16T00:00:00Z" }));
const messages = chatIds.map((id, index) => ({ id: `55000000-0000-4000-8000-00000000000${index + 1}`, chat_id: id,
  sequence: 1, role: "user", content: BANK_CHAT_TITLES[index], request_id: `66000000-0000-4000-8000-00000000000${index + 1}`,
  reply_to: null, model_id: "fixture-model", status: "complete", response: null, result_unavailable: false, created_at: "2026-11-16T00:00:00Z" }));
const error = (reply, status, code) => reply(status, { error: { code } });

export function installBankDemoFixture(base) {
  const original = base.route.bind(base);
  const state = { enabled: true, persona: "teller", failNext: null, hold: null, historyRevision: null,
    wrongOwner: false, pending: [], calls: [], peakHeld: 0, geometry: null,
    async release() { const held = this.pending.splice(0); for (const finish of held) await finish(); } };
  base.route = async (request, reply) => {
    const url = new URL(request.url);
    const bank = url.pathname.startsWith("/api/v1/bank-demo");
    // Two synthetic user-only saved histories exercise target selection without
    // submitting a new question or fabricating a generated SQL/model response.
    const chatIndex = chatIds.findIndex(id => url.pathname === `/api/v1/chats/${id}` || url.pathname === `/api/v1/chats/${id}/messages`);
    const seededRead = request.method === "GET" && (url.pathname === "/api/v1/chats" || chatIndex >= 0);
    if (!bank && !seededRead) return original(request, reply);
    if (!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(url.origin) || url.username || url.password) return error(reply, 403, "access_denied");
    if (!base.email) return error(reply, 401, "session_invalid");
    if (seededRead) {
      if (url.pathname === "/api/v1/chats") return reply(200, { items: structuredClone(chats), next_cursor: null });
      return reply(200, url.pathname.endsWith("/messages") ? { items: [structuredClone(messages[chatIndex])], older_cursor: null } : { chat: structuredClone(chats[chatIndex]) });
    }
    if (state.calls.length >= 80) return error(reply, 429, "rate_limited");
    state.calls.push({ method: request.method, path: url.pathname });
    if (url.search || url.hash) return error(reply, 422, "invalid_request");
    if (!state.enabled) return error(reply, 404, "not_found");
    if (!personas.includes(state.persona)) throw Error("bank_fixture_persona_invalid");
    const owner = base.session().user.id;
    const headers = Object.fromEntries(Object.entries(request.headers || {}).map(([name, value]) => [name.toLowerCase(), value]));
    let answer, kind;
    if (request.method === "GET" && url.pathname === "/api/v1/bank-demo/context" && !request.postData) {
      kind = "context"; answer = structuredClone(data.contexts[state.persona]);
    } else if (request.method === "POST" && url.pathname === "/api/v1/bank-demo/reports") {
      kind = "report";
      if (headers["x-csrf-token"] !== "fixture-session-csrf" || headers.origin !== url.origin) return error(reply, 403, "access_denied");
      let body;
      try { if (Buffer.byteLength(request.postData || "") > 8192) return error(reply, 413, "invalid_request"); body = JSON.parse(request.postData); }
      catch { return error(reply, 422, "invalid_request"); }
      if (!body || Array.isArray(body) || Object.keys(body).sort().join() !== "expected_source_revision,report_id,schemaVersion" || body.schemaVersion !== 1
        || typeof body.report_id !== "string" || typeof body.expected_source_revision !== "string") return error(reply, 422, "invalid_request");
      if (!data.contexts[state.persona].reports.some(item => item.id === body.report_id)) return error(reply, 403, "access_denied");
      if (body.expected_source_revision !== data.contexts[state.persona].context.sourceRevision) return error(reply, 409, "revision_conflict");
      answer = structuredClone(data.reports.find(item => item.result.reportId === body.report_id));
      if (!answer) return error(reply, 404, "not_found");
    } else return error(reply, 422, "invalid_request");
    if (state.failNext !== null) {
      const status = state.failNext; state.failNext = null;
      if (![403, 409, 503].includes(status)) throw Error("bank_fixture_fault_invalid");
      return error(reply, status, status === 409 ? "revision_conflict" : status === 403 ? "access_denied" : "temporarily_unavailable");
    }
    answer.owner_id = state.wrongOwner ? "99999999-9999-4999-8999-999999999999" : owner;
    assert.ok(Buffer.byteLength(JSON.stringify(answer)) <= 32768);
    const finish = () => reply(200, answer, state.historyRevision ? { "X-Aqua-History-Revision": state.historyRevision } : {});
    if (state.hold === kind) {
      if (state.pending.length >= 4) return error(reply, 429, "rate_limited");
      state.pending.push(finish); state.peakHeld = Math.max(state.peakHeld, state.pending.length); return;
    }
    return finish();
  };
  return state;
}
