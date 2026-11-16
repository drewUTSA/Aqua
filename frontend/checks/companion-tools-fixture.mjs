// Opt-in synthetic help contracts only. No DB, model, files, real account or mail.
export function installCompanionToolsFixture(base) {
  const original = base.route.bind(base), revision = "a".repeat(64);
  const state = { enabled: true, allowQuestion: true, abstain: false, hold: false, blockChunk: false,
    historyRevision: null, replyText: "Use the reviewed Aqua guide.", pending: [], calls: [],
    async release() { const held = this.pending.splice(0); for (const finish of held) await finish(); } };
  base.route = async (request, reply) => {
    const url = new URL(request.url);
    if (!url.pathname.startsWith("/api/v1/companion")) return original(request, reply);
    state.calls.push({ method: request.method, path: url.pathname });
    if (!base.email) return reply(401, { error: { code: "session_invalid" } });
    if (!state.enabled) return reply(404, { error: { code: "not_found" } });
    if (url.search) return reply(422, { error: { code: "invalid_request" } });
    if (request.method === "GET" && url.pathname === "/api/v1/companion/capabilities") {
      const tools = [{ id: "app_help", behavior: "reviewed_lookup" }];
      if (state.allowQuestion && base.canQuery) tools.push({ id: "authorized_question", behavior: "seed_draft" });
      return reply(200, { schemaVersion: 1, advisory: true, selection: "explicit", pack_revision: revision, capabilities: tools });
    }
    if (request.method !== "POST" || url.pathname !== "/api/v1/companion/help") return reply(404, { error: { code: "not_found" } });
    const headers = Object.fromEntries(Object.entries(request.headers || {}).map(([key, value]) => [key.toLowerCase(), value]));
    if (headers["x-csrf-token"] !== "fixture-session-csrf" || headers.origin !== url.origin) return reply(403, { error: { code: "access_denied" } });
    let body;
    try { if (Buffer.byteLength(request.postData || "") > 16384) throw new Error(); body = JSON.parse(request.postData); } catch { return reply(422, { error: { code: "invalid_request" } }); }
    if (!body || Object.keys(body).sort().join() !== "question,schemaVersion" || body.schemaVersion !== 1 || typeof body.question !== "string" || body.question.length > 2000) return reply(422, { error: { code: "invalid_request" } });
    const answer = { schemaVersion: 1, status: state.abstain ? "abstained" : "answered", capability_id: "app_help", method: "reviewed_lookup",
      message: state.abstain ? "No clear reviewed guide for this synthetic question." : state.replyText,
      citations: state.abstain ? [] : [{ id: "overview", title: "Reviewed Aqua guide", revision }], pack_revision: revision };
    const finish = () => reply(200, answer, state.historyRevision ? { "X-Aqua-History-Revision": state.historyRevision } : {});
    if (state.hold) { if (state.pending.length >= 8) return reply(429, {}); state.pending.push(finish); return; }
    return finish();
  };
  return state;
}
