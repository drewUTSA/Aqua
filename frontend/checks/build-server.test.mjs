import assert from "node:assert/strict";
import { createServer, request } from "node:http";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";
import { allowedHost, apiProxy, assetServer } from "../scripts/serve.mjs";
import { publicBuildEnv } from "../scripts/build.mjs";

test("development hosts match loopback, IP and the two configured Aqua names", () => {
  for (const host of ["localhost:5173", "dev.localhost", "[::1]:5173", "192.168.1.12", "aqua-ai.us", "www.aqua-ai.us"]) {
    assert.equal(allowedHost(host), true, host);
  }
  for (const host of [null, "", "other.example", "aqua-ai.us.example", "aqua-ai.us:66000"]) {
    assert.equal(allowedHost(host), false, host);
  }
});

test("only the three public build values survive file and process precedence", async () => {
  const directory = await mkdtemp(path.join(tmpdir(), "aqua-build-env-"));
  try {
    await writeFile(path.join(directory, ".env"), "VITE_AQUA_DEMO_MODE=true\nPRIVATE=ignored\n");
    await writeFile(path.join(directory, ".env.local"), "VITE_AQUA_UI_SHELL=legacy\n");
    await writeFile(path.join(directory, ".env.production.local"), "VITE_AQUA_USE_MOCK=true\n");
    assert.deepEqual(publicBuildEnv(directory, "production", { VITE_AQUA_USE_MOCK: "false", VITE_OTHER: "ignored" }), {
      VITE_AQUA_UI_SHELL: "legacy", VITE_AQUA_DEMO_MODE: "true", VITE_AQUA_USE_MOCK: "false",
    });
    assert.equal(publicBuildEnv(directory, "development", {}).VITE_AQUA_USE_MOCK, "false");
  } finally { await rm(directory, { recursive: true, force: true }); }
});

async function listen(server, t) {
  await new Promise((resolve, reject) => { server.once("error", reject); server.listen(0, "127.0.0.1", resolve); });
  t.after(() => new Promise(resolve => { server.close(resolve); server.closeAllConnections(); }));
  return server.address().port;
}

test("static requests only receive generated assets and the declared SPA routes", async t => {
  const files = new Map([["/index.html", Buffer.from("compiled")], ["/assets/test.js", Buffer.from("built") ]]);
  const port = await listen(assetServer({ files: () => files }), t);
  const get = (name, init) => fetch(`http://127.0.0.1:${port}${name}`, init);
  assert.equal(await (await get("/settings")).text(), "compiled");
  assert.equal((await get("/assets/test.js", { method: "HEAD" })).headers.get("Content-Type"), "text/javascript");
  for (const name of ["/src/main.jsx", "/.env", "/.aqua/manifest.json", "/package.json", "/api/v1/me"]) {
    assert.equal((await get(name)).status, 404, name);
  }
  assert.equal((await get("/settings", { method: "POST" })).status, 405);
});

test("fixed loopback proxy preserves method, cookies, CSRF, body, SSE and multiple response cookies", async t => {
  let observed;
  const api = createServer(async (req, res) => {
    const chunks = []; for await (const chunk of req) chunks.push(chunk);
    observed = { method: req.method, path: req.url, headers: req.headers, body: Buffer.concat(chunks).toString() };
    res.writeHead(202, { "Content-Type": "text/event-stream", "Set-Cookie": ["a=1", "b=2"] });
    res.write("data: waiting\n\n"); res.end("data: complete\n\n");
  });
  const apiPort = await listen(api, t);
  const port = await listen(assetServer({ files: () => new Map(), proxy: (req, res) => apiProxy(req, res, apiPort) }), t);
  const reply = await new Promise((resolve, reject) => {
    const req = request({ host: "127.0.0.1", port, method: "POST", path: "/api/demo?q=1", headers: {
      Cookie: "fixture=1", "X-CSRF-Token": "fixture", "X-Forwarded-Host": "unused", Connection: "x-test-hop", "X-Test-Hop": "unused",
    } }, async res => {
      const chunks = []; for await (const c of res) chunks.push(c);
      resolve({ status: res.statusCode, headers: res.headers, body: Buffer.concat(chunks).toString() });
    });
    req.on("error", reject); req.end("synthetic");
  });
  assert.equal(observed.method, "POST"); assert.equal(observed.path, "/api/demo?q=1");
  assert.equal(observed.body, "synthetic"); assert.equal(observed.headers.cookie, "fixture=1");
  assert.equal(observed.headers.host, `127.0.0.1:${apiPort}`); assert.equal(observed.headers["x-csrf-token"], "fixture");
  assert.equal(observed.headers["x-forwarded-host"], undefined); assert.equal(observed.headers["x-test-hop"], undefined);
  assert.equal(reply.status, 202); assert.deepEqual(reply.headers["set-cookie"], ["a=1", "b=2"]);
  assert.equal(reply.headers["content-type"], "text/event-stream"); assert.equal(reply.body, "data: waiting\n\ndata: complete\n\n");
});
