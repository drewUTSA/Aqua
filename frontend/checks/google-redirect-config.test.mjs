import assert from "node:assert/strict";
import test from "node:test";
import { fetchAuthConfig, AuthError } from "../src/services/authClient.js";

const config = { client_id: "fixture.apps.googleusercontent.com", nonce: "nonce", csrf_token: "csrf" };
for (const path of ["/api/auth/google/redirect", "https://attacker.example/callback", "//attacker.example", "/api/auth/google/redirect?next=other", null]) {
  test(`Google redirect configuration accepts only the fixed callback: ${path}`, async t => {
    t.mock.method(globalThis, "fetch", async () => new Response(JSON.stringify({ ...config, redirect_path: path }), { headers: { "Content-Type": "application/json" } }));
    if (path === "/api/auth/google/redirect") assert.deepEqual(await fetchAuthConfig(), { ...config, redirect_path: path });
    else await assert.rejects(fetchAuthConfig(), AuthError);
  });
}
