import { createServer, request as requestHttp } from "node:http";
import { isIP } from "node:net";
import { readFile } from "node:fs/promises";
import path from "node:path";
import { LOCAL_PATHS } from "../src/services/routes.js";

const mime = { ".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css",
  ".svg": "image/svg+xml", ".glb": "model/gltf-binary", ".png": "image/png", ".woff2": "font/woff2" };
const hosts = new Set(["localhost", "aqua-ai.us", "www.aqua-ai.us"]);

export function allowedHost(header) {
  if (typeof header !== "string" || !/^(?:\[[\da-f:]+\]|[a-z\d.-]+)(?::\d{1,5})?$/i.test(header)) return false;
  try {
    const host = new URL("http://" + header).hostname;
    return hosts.has(host) || host.endsWith(".localhost") || Boolean(isIP(host.replace(/^\[|\]$/g, "")));
  } catch { return false; }
}

export async function publicAssets(stats, directory) {
  const files = new Map();
  for (const { name } of stats.compilation.getAssets()) {
    if (name !== "index.html" && !/^assets\/[\w.-]+$/.test(name)) continue;
    if (!mime[path.extname(name)]) continue;
    files.set("/" + name, await readFile(path.join(directory, name)));
  }
  if (!files.has("/index.html")) throw new Error("missing_compiled_html");
  return files;
}

function proxyHeaders(headers) {
  const drop = new Set(["connection", "proxy-connection", "keep-alive", "transfer-encoding", "te",
    "trailer", "upgrade", "proxy-authorization", "proxy-authenticate", "forwarded",
    ...String(headers.connection || "").toLowerCase().split(",").map(name => name.trim())]);
  return Object.fromEntries(Object.entries(headers).filter(([name]) => !drop.has(name) && !name.startsWith("x-forwarded-")));
}

export function apiProxy(req, res, port = 8000) {
  const upstream = requestHttp({ hostname: "127.0.0.1", port, method: req.method, path: req.url,
    headers: { ...proxyHeaders(req.headers), host: `127.0.0.1:${port}` }, timeout: 240000 }, reply => {
    res.writeHead(reply.statusCode, proxyHeaders(reply.headers));
    reply.on("error", () => res.destroy());
    reply.pipe(res);
  });
  upstream.on("timeout", () => upstream.destroy());
  upstream.on("error", () => {
    if (!res.headersSent) { res.writeHead(502); res.end(); } else res.destroy();
  });
  req.on("error", () => upstream.destroy());
  res.on("close", () => { if (!res.writableFinished) upstream.destroy(); });
  req.pipe(upstream);
}

// Only compilation assets and approved app routes can produce bytes. The URL
// never becomes a file path. The test fixture provides no API proxy.
export function assetServer({ files, proxy, deny, onReload }) {
  return createServer({ requestTimeout: 240000 }, (req, res) => {
    const finish = status => { res.writeHead(status); res.end(); };
    if (!allowedHost(req.headers.host)) return finish(403);
    if (!req.url?.startsWith("/") || req.url.startsWith("//") || req.url.includes("\\")) return finish(400);
    let pathname;
    try { pathname = new URL(req.url, "http://localhost").pathname; } catch { return finish(400); }
    if (pathname === "/api" || pathname.startsWith("/api/")) return proxy ? proxy(req, res) : finish(404);
    if (!["GET", "HEAD"].includes(req.method)) return finish(405);
    if (req.method === "GET" && pathname === "/__aqua_reload" && onReload) return onReload(req, res);
    const name = LOCAL_PATHS.has(pathname) ? "/index.html" : pathname;
    const data = files().get(name);
    if (!data) return finish(404);
    if (deny?.(pathname)) return finish(503);
    res.writeHead(200, { "Content-Type": mime[path.extname(name)], "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer" });
    res.end(req.method === "HEAD" ? undefined : data);
  });
}
