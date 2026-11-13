// Disposable, synthetic APIs only. Every non-loopback request is intercepted.
import { createServer } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { makeFixture } from "../../frontend/checks/p05-browser-fixture.mjs";
import { googleStub } from "./google-stub.mjs";
import { redirectRoute } from "./redirect-route.mjs";

export async function setup(page, context) {
  const files = new Map();
  const root = new URL("../../frontend/dist/", import.meta.url);
  async function load(directory, prefix = "") {
    for (const entry of await readdir(directory, { withFileTypes: true })) {
      if (entry.isSymbolicLink()) throw new Error("fixture_symlink_rejected");
      const url = new URL(entry.name + (entry.isDirectory() ? "/" : ""), directory);
      if (entry.isDirectory()) await load(url, `${prefix}/${entry.name}`);
      else files.set(`${prefix}/${entry.name}`, await readFile(fileURLToPath(url)));
    }
  }
  await load(root);
  const fixture = makeFixture(), failures = [], external = [], blocked = new Set(), held = [];
  const counts = new Map();
  const origins = [];
  let setCookies = true, origin;
  const types = { js: "application/javascript", css: "text/css", svg: "image/svg+xml", html: "text/html", woff2: "font/woff2" };
  const server = createServer((req, res) => {
    const url = new URL(req.url, origin);
    const reply = (status, body, headers = {}) => {
      if (res.destroyed) return;
      const login = req.method === "POST" && ["/api/auth/google", "/api/v1/auth/password-login", "/api/auth/google/redirect-complete"].includes(url.pathname) && status === 200;
      const logout = url.pathname === "/api/auth/logout" && status === 204;
      if (setCookies && (login || logout)) headers["Set-Cookie"] = `aqua-fixture=${login ? "session" : ""}; Path=/; HttpOnly; SameSite=Lax${logout ? "; Max-Age=0" : ""}`;
      res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store", ...headers });
      res.end(status === 204 ? "" : JSON.stringify(body ?? {}));
    };
    if (url.pathname.startsWith("/api/")) {
      const key = `${req.method} ${url.pathname}`;
      counts.set(key, (counts.get(key) || 0) + 1);
      const inertRedirect = fixture.redirectMode && url.pathname === "/api/auth/google/redirect" && req.method === "POST";
      if (!["GET", "HEAD"].includes(req.method) && !inertRedirect) {
        const originValid = req.headers.origin === origin;
        const refererPrivate = !req.headers.referer || req.headers.referer === origin + "/";
        origins.push({ originValid, refererPrivate });
        if (!originValid || !refererPrivate) return reply(403, {});
      }
      if (blocked.has(url.pathname)) { held.push(res); return; }
      if (url.pathname === "/api/auth/me" && !req.headers.cookie?.split("; ").includes("aqua-fixture=session")) return reply(401, {});
      void (async () => {
        const chunks = []; let size = 0;
        for await (const chunk of req) {
          size += chunk.length;
          if (size > 8192) return reply(413, {});
          chunks.push(chunk);
        }
        const raw = Buffer.concat(chunks).toString("utf8");
        if (redirectRoute({ req, res, url, raw, origin, fixture, reply })) return;
        await fixture.route({ url: url.href, method: req.method, headers: req.headers, postData: raw }, (status, body, headers) => {
          if (url.pathname === "/api/auth/config" && fixture.redirectMode && status === 200) {
            body.redirect_path = "/api/auth/google/redirect";
            headers = { ...headers, "Set-Cookie": "aqua-fixture-login=challenge; Path=/; HttpOnly; SameSite=Lax" };
          }
          return reply(status, body, headers);
        });
      })().catch(() => { failures.push("fixture_exception"); reply(503, {}); });
      return;
    }
    const key = files.has(url.pathname) ? url.pathname : "/index.html";
    res.writeHead(200, { "Content-Type": types[key.split(".").pop()] || "application/octet-stream", "Cache-Control": "no-store" });
    res.end(files.get(key));
  });
  await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
  origin = `http://127.0.0.1:${server.address().port}`;
  page.on("pageerror", () => failures.push("page_exception"));
  await context.route("**/*", async route => {
    const url = new URL(route.request().url());
    if (url.href === "https://accounts.google.com/gsi/client") {
      return route.fulfill({ status: 200, contentType: "application/javascript", body: googleStub });
    }
    if (url.origin !== origin) { external.push(url.origin); return route.abort(); }
    return route.continue();
  });
  return { fixture, origin, failures, external, blocked, origins,
    attempts(path, method = "POST") { return counts.get(`${method} ${path}`) || 0; },
    denyCookies() { setCookies = false; },
    async close() {
      fixture.clearHolds(); await fixture.release("google"); await fixture.release("reset");
      for (const res of held) res.destroy();
      server.closeAllConnections();
      await new Promise(resolve => server.close(resolve));
    }
  };
}
