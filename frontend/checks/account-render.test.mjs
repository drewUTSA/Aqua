import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";
import { accountMethods, accountSessions } from "../src/settings/accountContract.js";

const compiled = new Map();
async function jsxModule(url) {
  if (compiled.has(url.href)) return compiled.get(url.href);
  const transformed = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname, { loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const specifier = match[1];
    imports.set(specifier, specifier === "react" ? import.meta.resolve("react")
      : specifier.endsWith(".jsx") ? await jsxModule(new URL(specifier, url))
        : new URL(specifier, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, specifier) => `from ${JSON.stringify(imports.get(specifier))}`);
  const result = "data:text/javascript;base64," + Buffer.from(code).toString("base64");
  compiled.set(url.href, result); return result;
}
const { default: AccountFoundation, AccountMethods, AccountSessions } = await import(await jsxModule(new URL("../src/settings/AccountFoundation.jsx", import.meta.url)));
const { default: SettingsInformation } = await import(await jsxModule(new URL("../src/settings/SettingsInformation.jsx", import.meta.url)));
const { default: AccountSecurityDialog } = await import(await jsxModule(new URL("../src/settings/AccountSecurityDialog.jsx", import.meta.url)));
const owner = "11111111-1111-4111-8111-111111111111";
const auth = { demoMode: false, status: "authenticated", user: { id: owner, name: "Auth cached name", email: "example@example.invalid" }, csrfToken: "test-only" };
const caps = { profile_edit: true, method_list: true, session_list: true, recent_proof: false, email_change: false, password_change: false, password_add: false,
  google_link: false, google_unlink: false, session_revoke: false, sessions_revoke_all: false, notification_delivery: false };
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test("Account Settings SSR has explicit read-only reviews and never starts a request", (t) => {
  const calls = t.mock.method(globalThis, "fetch", () => { throw Error("Unexpected network request"); });
  const html = render(AccountFoundation, { auth });
  assert.match(html, /data-account-foundation/); assert.match(html, /Review methods/); assert.match(html, /Review sessions/);
  assert.doesNotMatch(html, /data-account-edit-name|Auth cached name|This session/);
  assert.match(html, /Preference Save, Cancel, import and reset do not change your account/);
  assert.match(html, /adding a first password and linking or removing sign-in methods are not available yet/);
  assert.equal(calls.mock.calls.length, 0);
});

test("demo and absent-identity rendering cannot claim verified profile or session controls", (t) => {
  const calls = t.mock.method(globalThis, "fetch", () => { throw Error("Unexpected network request"); });
  for (const value of [{ ...auth, demoMode: true }, { ...auth, user: null }]) {
    const html = render(AccountFoundation, { auth: value });
    assert.match(html, /require a verified signed-in account/);
    assert.doesNotMatch(html, /data-account-load|Verified|data-account-name-input/);
  }
  assert.equal(calls.mock.calls.length, 0);
});

test("other Settings categories do not mount account resources", (t) => {
  const calls = t.mock.method(globalThis, "fetch", () => { throw Error("Unexpected network request"); });
  for (const category of ["chat", "workspace", "accessibility", "notifications", "region", "privacy", "appearance"]) {
    assert.doesNotMatch(render(SettingsInformation, { category, auth }), /data-account-foundation|data-account-load/);
  }
  assert.equal(calls.mock.calls.length, 0);
});

test("actual method DOM distinguishes linked from available and exposes no management actions", () => {
  const data = accountMethods({ schemaVersion: 1, password: { linked: true, available: false, changed_at: "2026-10-26T12:00:00Z" },
    google: { linked: true, available: true, identities: [{ id: owner, linked_at: "2026-10-26T12:00:00Z" }] }, capabilities: caps });
  const html = render(AccountMethods, { data });
  assert.match(html, /Password<\/dt><dd>Linked/); assert.match(html, /Sign-in currently unavailable/);
  assert.match(html, /Google<\/dt><dd>Linked · 1 identity/); assert.match(html, /Sign-in available/);
  assert.doesNotMatch(html, /<button|<a |11111111|changed_at|capabilities/);
});

test("session DOM labels current and others honestly, uses preference formatting and no private identifiers", () => {
  const item = { id: owner, method: "password", device_label: "Private raw device string", current: true,
    created_at: "2026-10-26T12:00:00Z", authenticated_at: "2026-10-26T12:00:00Z", last_activity_at: "2026-10-26T12:05:00Z",
    idle_expires_at: "2026-10-26T13:00:00Z", absolute_expires_at: "2026-10-27T12:00:00Z" };
  const data = accountSessions({ schemaVersion: 1, items: [item], capabilities: { revoke_one: false, revoke_all: false } });
  const html = render(AccountSessions, { data, preferences: { locale: "en-GB", timezone: "UTC", date_style: "medium", time_format: "24" } });
  assert.match(html, /This session/); assert.match(html, /Unknown device/); assert.match(html, /No other active sessions/);
  assert.match(html, /26 Oct 2026/); assert.match(html, /dateTime="2026-10-26T12:05:00Z"/);
  assert.doesNotMatch(html, /11111111|Private raw|<button|<a |IP address|location|MFA|revoke_one/);
});

test("initial security dialogs require current-password verification and never embed proof or future secrets", t => {
  const calls = t.mock.method(globalThis, "fetch", () => { throw Error("Unexpected request"); });
  for (const action of [{ operation: "password_change" }, { operation: "sessions_revoke_all" },
    { operation: "session_revoke", session: { id: owner, current: false, device_label: "Desktop browser" } }]) {
    const html = render(AccountSecurityDialog, { auth, action, allowed: true, onClose() {}, onSessions() {}, onRevoked() {} });
    assert.match(html, /data-account-security-phase="verify"/); assert.match(html, /type="password"/); assert.match(html, /autoComplete="current-password"/);
    assert.match(html, /<button type="button">Cancel<\/button>/); assert.match(html, /data-account-verify-password/);
    assert.doesNotMatch(html, /proof_token|challenge_token|v2\.|data-account-confirm-security|data-account-new-password|11111111|value=/);
  }
  assert.equal(calls.mock.calls.length, 0);
});

test("unavailable security dialog keeps Cancel available without advertising a supported proof action", () => {
  const html = render(AccountSecurityDialog, { auth, action: { operation: "password_change" }, allowed: false, onClose() {} });
  assert.match(html, /This security action is currently unavailable/);
  assert.match(html, /data-account-verify-password="true" disabled=""/);
  assert.doesNotMatch(html, /<button[^>]*disabled[^>]*>Cancel/);
});

test("session actions render only as explicit separately gated buttons", () => {
  const session = { id: owner, method: "password", device_label: "Desktop browser", current: true,
    created_at: "2026-10-26T12:00:00Z", authenticated_at: "2026-10-26T12:00:00Z", last_activity_at: "2026-10-26T12:05:00Z",
    idle_expires_at: "2026-10-26T13:00:00Z", absolute_expires_at: "2026-10-27T12:00:00Z" };
  const data = accountSessions({ schemaVersion: 1, items: [session], capabilities: { revoke_one: true, revoke_all: true } });
  const disabled = render(AccountSessions, { data, preferences: {}, onRevoke() {}, canRevoke: () => false });
  assert.match(disabled, /data-account-revoke-session="current" disabled=""/);
  assert.doesNotMatch(disabled, /11111111/);
  const available = render(AccountSessions, { data, preferences: {}, onRevoke() {}, canRevoke: () => true });
  assert.match(available, /End this session/); assert.doesNotMatch(available, /disabled=""/);
});
