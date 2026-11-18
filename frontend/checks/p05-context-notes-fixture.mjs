// Opt-in intercepted frontend double. Never a database, grant or retention proof.
import { createHash } from "node:crypto";

export const NOTE_IDS = Object.freeze({ first: "51000000-0000-4000-8000-000000000001", second: "51000000-0000-4000-8000-000000000002",
  unavailable: "51000000-0000-4000-8000-000000000003", created: "51000000-0000-4000-8000-000000000004" });
export const NOTE_CHAT_TITLES = Object.freeze(["Saved notes sample A", "Saved notes sample B"]);
export const NOTES_GOLD = Object.freeze({ label: "Dispatch definition", body: "For this demo, completed means reviewed.\nUse returned rows only.",
  second: "Check missing values before comparing periods.", newLabel: "Review checklist", newBody: "Review totals with the data owner.\nThen choose a new question.",
  counterText: "é🙂\n", correction: "Review totals with the data owner.\nCheck missing values too.", applied: "My reviewed question about the returned rows." });
const when = "2026-11-17T18:00:00Z", uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const chats = ["52000000-0000-4000-8000-000000000001", "52000000-0000-4000-8000-000000000002"].map((id, i) => ({ id,
  title: NOTE_CHAT_TITLES[i], project_id: null, archived: false, revision: 1, message_count: 2, created_at: when, last_activity_at: when }));
const table = { status: "success", message: "Original fictional saved table.", sql: "/* original UI fixture */", visualizations: [], kpis: [],
  tables: [{ id: "sample", title: "Original demonstration rows", columns: [{ key: "category", label: "Category", type: "string" }, { key: "count", label: "Returned count", type: "number" }],
    rows: [{ category: "Reviewed", count: 3 }, { category: "Waiting", count: 2 }] }] };
const limits = { active_notes: 20, label_characters: 120, label_bytes: 512, body_utf16_units: 2000, body_bytes: 2048, draft_utf16_units: 2000, draft_bytes: 8000 };
const sha = value => createHash("sha256").update(JSON.stringify(value)).digest("hex");
export const NOTES_FIXTURE_SHA256 = sha({ notes: NOTES_GOLD, chats, table, limits });
const exact = (value, names) => value && typeof value === "object" && !Array.isArray(value) && Object.keys(value).sort().join() === [...names].sort().join();
const revision = value => Number.isSafeInteger(value) && value > 0;
const label = value => typeof value === "string" && value.trim() === value && value.length > 0 && [...value].length <= 120
  && Buffer.byteLength(value) <= 512 && !/[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(value);
const text = value => typeof value === "string" && value.trim().length > 0 && value.length <= 2000 && Buffer.byteLength(value) <= 2048
  && !/[\p{Cc}\p{Cf}\p{Cs}]/u.test(value.replace(/[\t\n]/g, ""));
const fields = value => ["note", "metric_definition"].includes(value.kind) && label(value.label) && text(value.body);
const failure = (reply, status) => reply(status, { error: { code: ({ 401: "session_invalid", 403: "access_denied", 404: "not_found", 409: "revision_conflict", 429: "rate_limited", 503: "service_unavailable" })[status] || "invalid_request" } });
function history(index, allowed) {
  const request = `53000000-0000-4000-8000-00000000000${index + 1}`, input = `54000000-0000-4000-8000-00000000000${index + 1}`;
  const common = { chat_id: chats[index].id, request_id: request, model_id: "fixture-model", status: "complete", created_at: when };
  return [{ ...common, id: input, sequence: 1, role: "user", content: "Show the original fictional saved rows.", reply_to: null, response: null, result_unavailable: false },
    { ...common, id: `55000000-0000-4000-8000-00000000000${index + 1}`, sequence: 2, role: "aqua", content: "", reply_to: input,
      response: allowed ? structuredClone(table) : null, result_unavailable: !allowed }];
}

export function installContextNotesFixture(base) {
  const original = base.route.bind(base), stores = new Map(); let seeded = false;
  const state = { enabled: true, hold: null, failNext: null, failAfterWrite: false, blockChunk: false, chunkDenials: 0,
    responseHistoryRevision: null, requiredHistoryRevision: null, scopeEpoch: 0, pending: [], calls: [], peakHeld: 0, geometry: null,
    async release() { for (const finish of this.pending.splice(0)) await finish(); } };
  const scope = owner => ({ id: sha([owner, base.canQuery, state.scopeEpoch]), can_use: base.canQuery });
  function store(owner) {
    if (!stores.has(owner)) {
      const notes = new Map();
      if (!seeded) {
        notes.set(NOTE_IDS.first, { id: NOTE_IDS.first, revision: 2, kind: "metric_definition", label: NOTES_GOLD.label, body: NOTES_GOLD.body, created_at: when, updated_at: when, scope: scope(owner).id });
        notes.set(NOTE_IDS.second, { id: NOTE_IDS.second, revision: 1, kind: "note", label: "Weekly review reminder", body: NOTES_GOLD.second, created_at: when, updated_at: when, scope: scope(owner).id });
        notes.set(NOTE_IDS.unavailable, { id: NOTE_IDS.unavailable, revision: 4, scope: "unavailable" }); seeded = true;
      }
      stores.set(owner, { notes, requests: new Map() });
    }
    return stores.get(owner);
  }
  base.route = async (request, reply) => {
    const url = new URL(request.url), isNotes = /^\/api\/v1\/me\/context-notes(?:\/|$)/.test(url.pathname);
    const chatIndex = chats.findIndex(chat => url.pathname === `/api/v1/chats/${chat.id}` || url.pathname === `/api/v1/chats/${chat.id}/messages`);
    const saved = request.method === "GET" && (url.pathname === "/api/v1/chats" || chatIndex >= 0);
    if (!isNotes && !saved) return original(request, reply);
    if (!/^http:\/\/127\.0\.0\.1:[1-9][0-9]{0,4}$/.test(url.origin) || url.username || url.password) return failure(reply, 403);
    if (!base.email) return failure(reply, 401);
    const owner = base.session().user.id; if (typeof owner !== "string" || !uuid.test(owner)) throw Error("notes_fixture_owner_not_uuid");
    if (saved) return reply(200, url.pathname === "/api/v1/chats" ? { items: structuredClone(chats), next_cursor: null }
      : url.pathname.endsWith("/messages") ? { items: history(chatIndex, base.canQuery), older_cursor: null } : { chat: structuredClone(chats[chatIndex]) });
    if (state.calls.length >= 80) return failure(reply, 429);
    const match = /^\/api\/v1\/me\/context-notes(?:\/([a-f0-9-]{36})(?:\/(forget|prepare))?)?$/.exec(url.pathname);
    if (!match || match[1] && !uuid.test(match[1]) || url.search || url.hash) return failure(reply, 422);
    const action = !match[1] ? request.method === "GET" ? "list" : request.method === "POST" ? "create" : null
      : match[2] ? request.method === "POST" ? match[2] : null : request.method === "GET" ? "read" : request.method === "PATCH" ? "save" : null;
    if (!action) return failure(reply, 422);
    state.calls.push({ action, method: request.method, path: url.pathname });
    if (!state.enabled) return failure(reply, 404);
    const headers = Object.fromEntries(Object.entries(request.headers || {}).map(([key, value]) => [key.toLowerCase(), value]));
    if (state.requiredHistoryRevision && headers["x-aqua-history-revision"] !== state.requiredHistoryRevision) return failure(reply, 409);
    if (request.method !== "GET" && (headers.origin !== url.origin || headers["x-csrf-token"] !== "fixture-session-csrf")) return failure(reply, 403);
    if (request.method === "GET" && request.postData) return failure(reply, 422);
    if (state.pending.length >= 4 && (state.hold === action || state.hold === "all")) return failure(reply, 429);
    if (state.failNext !== null) { const status = state.failNext; state.failNext = null; if (![403,409,503].includes(status)) throw Error("notes_fixture_failure_invalid"); return failure(reply, status); }
    let body;
    if (request.method !== "GET") {
      const raw = request.postData ?? ""; if (typeof raw !== "string") return failure(reply, 422); if (Buffer.byteLength(raw) > 8192) return failure(reply, 413);
      try { body = JSON.parse(raw); } catch { return failure(reply, 422); }
      // The browser sends compact JSON.stringify bodies; this double also rejects duplicate fields.
      if (JSON.stringify(body) !== raw) return failure(reply, 422);
      const names = action === "create" ? ["schemaVersion","client_request_id","expected_scope_id","kind","label","body"]
        : action === "save" ? ["schemaVersion","expected_scope_id","revision","kind","label","body"] : ["schemaVersion","expected_scope_id","revision"];
      if (!exact(body, names) || body.schemaVersion !== 1 || action === "create" && (typeof body.client_request_id !== "string" || !uuid.test(body.client_request_id))
        || action !== "create" && !revision(body.revision) || ["create","save"].includes(action) && !fields(body)) return failure(reply, 422);
      if (body.expected_scope_id !== scope(owner).id) return failure(reply, 409);
    }
    if (!["list","forget"].includes(action) && !base.canQuery) return failure(reply, 403);
    const data = store(owner), current = scope(owner), selected = data.notes.get(match[1]);
    const available = note => !note.deleted && note.scope === current.id && current.can_use;
    const full = note => Object.fromEntries(["id","revision","kind","label","body","created_at","updated_at"].map(key => [key, note[key]]));
    const metadata = note => available(note) ? { ...Object.fromEntries(["id","revision","kind","label","created_at","updated_at"].map(key => [key,note[key]])), availability: "available" }
      : { id: note.id, revision: note.revision, availability: "unavailable", label: "Unavailable saved context", kind: null, created_at: null, updated_at: null };
    let payload, status = 200;
    if (action === "list") payload = { items: [...data.notes.values()].filter(note => !note.deleted).sort((a,b) => b.id.localeCompare(a.id)).map(metadata), limits };
    else if (action === "create") {
      const fingerprint = sha(body), existing = data.requests.get(body.client_request_id);
      if (existing) {
        if (existing.fingerprint !== fingerprint || data.notes.get(existing.id)?.deleted) return failure(reply, 409);
        payload = { note: full(data.notes.get(existing.id)) };
      } else {
        if ([...data.notes.values()].filter(note => !note.deleted).length >= 20 || data.notes.has(NOTE_IDS.created)) return failure(reply, 429);
        const value = { id: NOTE_IDS.created, revision: 1, kind: body.kind, label: body.label, body: body.body, created_at: when, updated_at: when, scope: current.id };
        data.notes.set(value.id, value); data.requests.set(body.client_request_id, { id: value.id, fingerprint }); payload = { note: full(value) }; status = 201;
      }
    } else {
      if (!selected || selected.deleted || action !== "forget" && !available(selected)) return failure(reply, 404);
      if (action !== "read" && body.revision !== selected.revision) return failure(reply, 409);
      if (action === "read") payload = { note: full(selected) };
      if (action === "save") { Object.assign(selected, { kind: body.kind, label: body.label, body: body.body, revision: selected.revision + 1 }); payload = { note: full(selected) }; }
      if (action === "forget") { const deleted = { id: selected.id, revision: selected.revision + 1 }; data.notes.set(selected.id, { ...deleted, deleted: true }); payload = { deleted }; }
      if (action === "prepare") payload = { source: Object.fromEntries(["id","revision","kind","label"].map(key => [key,selected[key]])), draft: selected.body, requires_review: true };
    }
    const answer = structuredClone({ schemaVersion: 1, owner_id: owner, scope: current, unverified: true, execution_enabled: false, ...payload });
    if (Buffer.byteLength(JSON.stringify(answer)) > 32768) throw Error("notes_fixture_reply_oversized");
    const uncertain = state.failAfterWrite && ["create","save","forget"].includes(action); if (uncertain) state.failAfterWrite = false;
    const finish = () => uncertain ? failure(reply, 503) : reply(status, answer, state.responseHistoryRevision ? { "X-Aqua-History-Revision": state.responseHistoryRevision } : {});
    if (state.hold === action || state.hold === "all") { state.pending.push(finish); state.peakHeld = Math.max(state.peakHeld,state.pending.length); return; }
    return finish();
  };
  return state;
}
