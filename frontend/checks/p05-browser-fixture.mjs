// Synthetic contract fixture only. It never opens a DB, provider or mailbox.
import { workspaceFixture } from "./p06-browser-fixture.mjs";
export const PASSWORD = "Fixture orbital meadow password 27";
export const EMAIL_A = "reader-a@example.test";
export const EMAIL_B = "reader-b@example.test";
export const VERIFY_PROOF = "v".repeat(43);
export const RESET_PROOF = "r".repeat(43);
export const ACK = { detail: "If this address is eligible, account instructions will be sent." };
const ids = { [EMAIL_A]: "7506fb3d-1119-4b29-8c57-5ea696a739a1", [EMAIL_B]: "25a433e1-8ca6-4e02-a49c-b57aac5983a8" };
const actions = {
  "/api/v1/auth/registrations": "registration", "/api/v1/auth/email-verifications": "verification",
  "/api/v1/auth/password-login": "login", "/api/v1/auth/password-reset-requests": "reset-request",
  "/api/v1/auth/password-resets": "reset"
};
export const GOOGLE_STUB = `(() => {
  let settings;
  window.google={accounts:{id:{initialize(value){settings=value},disableAutoSelect(){},
    renderButton(container){const button=document.createElement('button');button.type='button';
      button.textContent='Continue with Google';button.dataset.testid='fixture-google-button';
      button.onclick=()=>settings.callback({credential:'fixture-google-credential'});container.append(button)}
  }}};
  window.__fixtureScriptExecuted=0;
  window.__fixtureSessionEvents=[];
  const channel=new BroadcastChannel('aqua-session-events');
  channel.onmessage=event=>{if(window.__fixtureSessionEvents.length<50)window.__fixtureSessionEvents.push(event.data)};
})();`;

export function makeFixture() {
  let workspace;
  return {
    email: null, canQuery: true, google: "ready", passwordEnabled: true,
    holdLogin: false, holdLogout: false, holdQuery: false, holdReset: false, logoutFailure: false,
    nextError: null, challenge: null, sequence: 0, calls: [], held: [], proofs: new Set(),
    queryMessage: "Synthetic answer for this account.", forbiddenCalls: 0,
    session(email = this.email) {
      return { user: { id: ids[email], email, name: email === EMAIL_A ? "Fixture Reader A" : "Fixture Reader B", picture: "" },
        csrf_token: "fixture-session-csrf", can_query: this.canQuery,
        capabilities: { google_login: true, password_login: this.passwordEnabled, durable_sessions: true } };
    },
    count(path, method = "POST") { return this.calls.filter((call) => call.path === path && call.method === method).length; },
    queryCount() { return this.calls.filter((call) => call.method === "POST" && (call.path === "/api/query" || /^\/api\/v1\/chats(?:\/[^/]+\/messages(?:\/[^/]+\/retries)?)?$/.test(call.path))).length; },
    securityCallCount() { return this.calls.filter((call) => call.path.startsWith("/api/auth/") || call.path.startsWith("/api/v1/auth/")).length + this.queryCount(); },
    async route(request, reply) {
      const url = new URL(request.url);
      const headers = Object.fromEntries(Object.entries(request.headers).map(([key, value]) => [key.toLowerCase(), value]));
      let body = null;
      if (request.postData) {
        if (Buffer.byteLength(request.postData) > 8192) { this.forbiddenCalls++; return reply(413, {}); }
        try { body = JSON.parse(request.postData); } catch { this.forbiddenCalls++; return reply(400, {}); }
      }
      // Submitted values are held only in this ephemeral fixture; reports retain
      // aggregate method/path counts and booleans, never request bodies or proofs.
      const call = { path: url.pathname, method: request.method, action: url.searchParams.get("action"), body, headers };
      this.calls.push(call);
      workspace ||= workspaceFixture(this);
      if (await workspace({ url, method: request.method, body, headers }, reply)) return;
      if (url.pathname === "/api/auth/me" && request.method === "GET") return this.email ? reply(200, this.session()) : reply(401, {});
      if (url.pathname === "/api/models" && request.method === "GET") return reply(200, { models: [{ id: "fixture-model", name: "Fixture model" }] });
      if (url.pathname === "/api/auth/config" && request.method === "GET") {
        const finish = () => reply(this.google === "error" ? 503 : 200, this.google === "error" ? { detail: "private-server" } : {
          client_id: "fixture.apps.googleusercontent.com", nonce: "fixture-google-nonce", csrf_token: "fixture-google-csrf",
          capabilities: { google_login: true, password_login: this.passwordEnabled, durable_sessions: true }
        });
        if (this.google === "hold") { this.held.push({ kind: "google", finish }); return; }
        return finish();
      }
      if (url.pathname === "/api/auth/google" && request.method === "POST") {
        if (body?.credential !== "fixture-google-credential" || headers["x-csrf-token"] !== "fixture-google-csrf") return reply(403, {});
        this.email = EMAIL_A;
        return reply(200, this.session());
      }
      if (url.pathname === "/api/auth/logout" && request.method === "POST") {
        if (headers["x-csrf-token"] !== "fixture-session-csrf") return reply(403, {});
        const finish = () => {
          if (this.logoutFailure) return reply(503, { detail: "private-server" });
          this.email = null;
          return reply(204);
        };
        if (this.holdLogout) { this.held.push({ kind: "logout", finish }); return; }
        return finish();
      }
      if (url.pathname === "/api/v1/auth/bootstrap" && request.method === "GET") {
        if (!this.passwordEnabled) return reply(503, { detail: "private-server disabled flag" });
        if (!Object.values(actions).includes(call.action)) { this.forbiddenCalls++; return reply(422, {}); }
        this.challenge = { action: call.action, csrf: `fixture-action-${++this.sequence}` };
        return reply(200, { csrf_token: this.challenge.csrf,
          capabilities: { google_login: this.google === "ready", password_login: true, durable_sessions: true },
          password_policy: { minimum_length: 15, maximum_length: 128, normalization: "NFC" } });
      }
      if (Object.hasOwn(actions, url.pathname) && request.method === "POST") {
        const action = actions[url.pathname];
        const challenge = this.challenge;
        this.challenge = null;
        if (!challenge || challenge.action !== action || headers["x-csrf-token"] !== challenge.csrf) return reply(403, {});
        if (this.nextError?.path === url.pathname) {
          const error = this.nextError; this.nextError = null;
          const finish = () => {
            if (action === "reset" && error.sessionsRevoked) this.email = null;
            return reply(error.status, { detail: "private-server diagnostic must not render" }, error.status === 429 ? { "Retry-After": "1" } : {});
          };
          if (action === "reset" && this.holdReset) { this.held.push({ kind: "reset", finish }); return; }
          return finish();
        }
        if (action === "registration" || action === "reset-request") {
          if (!body || Object.keys(body).length !== 1 || typeof body.email !== "string") { this.forbiddenCalls++; return reply(422, {}); }
          return reply(202, ACK);
        }
        if (action === "login") {
          const finish = () => {
            if (!Object.hasOwn(ids, body?.email ?? "") || body?.password !== PASSWORD) return reply(401, {});
            this.email = body.email;
            return reply(200, this.session());
          };
          if (this.holdLogin) { this.held.push({ kind: "login", finish }); return; }
          return finish();
        }
        const expected = action === "verification" ? VERIFY_PROOF : RESET_PROOF;
        if (body?.token !== expected || this.proofs.has(expected)) return reply(400, {});
        if (body?.password !== PASSWORD) return reply(422, {});
        this.proofs.add(expected);
        if (action === "reset") this.email = null;
        return reply(204);
      }
      if (url.pathname === "/api/query" && request.method === "POST") {
        if (!this.email || !this.canQuery) { this.forbiddenCalls++; return reply(this.email ? 403 : 401, {}); }
        if (headers["x-csrf-token"] !== "fixture-session-csrf") { this.forbiddenCalls++; return reply(403, {}); }
        const message = this.queryMessage;
        const finish = () => {
          if (this.nextError?.path === "/api/query") { const status = this.nextError.status; this.nextError = null; return reply(status, {}); }
          return reply(200, { status: "success", message, sql: "SELECT 1 AS synthetic_value", model: "fixture-model", tables: [], visualizations: [], kpis: [] });
        };
        if (this.holdQuery) { this.held.push({ kind: "query", finish }); return; }
        return finish();
      }
      this.forbiddenCalls++;
      return reply(404, {});
    },
    async release(kind) {
      const matching = this.held.filter((entry) => entry.kind === kind);
      this.held = this.held.filter((entry) => entry.kind !== kind);
      await Promise.all(matching.map((entry) => entry.finish()));
    },
    clearHolds() { this.google = "ready"; this.holdLogin = this.holdLogout = this.holdQuery = this.holdReset = false; }
  };
}
