import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { EMAIL_A } from "../../frontend/checks/p05-browser-fixture.mjs";

const PATH = "/api/auth/google/redirect";
const hasCookie = (req, value) => req.headers.cookie?.split("; ").includes(value);

export function redirectRoute({ req, res, url, raw, origin, fixture, reply }) {
  if (!fixture.redirectMode || ![PATH, PATH + "-state", PATH + "-complete"].includes(url.pathname)) return false;
  if (url.pathname === PATH && req.method === "POST") {
    const body = Object.fromEntries(new URLSearchParams(raw));
    const result = spawnSync(process.env.AQUA_CHECK_PYTHON || "python3", [fileURLToPath(new URL("render_bridge.py", import.meta.url))], {
      input: JSON.stringify(body), encoding: "utf8", timeout: 3000, maxBuffer: 128 * 1024
    });
    if (result.status !== 0) throw new Error("synthetic_bridge_render_failed");
    const document = JSON.parse(result.stdout);
    res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", ...document.headers }); res.end(document.html);
    return true;
  }
  if (url.pathname === PATH + "-state" && req.method === "GET") {
    reply(hasCookie(req, "aqua-fixture-login=challenge") && hasCookie(req, "g_csrf_token=fixture-google-csrf") ? 200 : 403,
      { csrf_token: "fixture-google-csrf" });
    return true;
  }
  if (url.pathname === PATH + "-complete" && req.method === "POST") {
    const body = JSON.parse(raw);
    if (req.headers.origin !== origin || req.headers["x-csrf-token"] !== "fixture-google-csrf"
      || !hasCookie(req, "aqua-fixture-login=challenge") || !hasCookie(req, "g_csrf_token=fixture-google-csrf")
      || body.credential !== "fixture-google-credential" || body.g_csrf_token !== "fixture-google-csrf") {
      reply(403, {}); return true;
    }
    if (fixture.redirectFailure) { reply(503, {}); return true; }
    fixture.email = EMAIL_A; reply(200, fixture.session()); return true;
  }
  reply(405, {}); return true;
}
