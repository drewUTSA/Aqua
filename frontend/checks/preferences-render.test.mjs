import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";

// Render the real provider/component pair with the locked JSX compiler. Loading
// it as data modules avoids DOM/network fixtures and catches context collisions.
const compiled = new Map();
async function jsxModule(url) {
  if (compiled.has(url.href)) return compiled.get(url.href);
  const transformed = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname, { loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const replacements = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const specifier = match[1];
    replacements.set(specifier, specifier === "react" ? import.meta.resolve("react")
      : specifier.endsWith(".jsx") ? await jsxModule(new URL(specifier, url))
        : specifier.endsWith(".svg") ? "data:text/javascript;base64," + Buffer.from(`export default ${JSON.stringify(new URL(specifier, url).href)}`).toString("base64")
          : new URL(specifier, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, specifier) => `from ${JSON.stringify(replacements.get(specifier))}`);
  const result = "data:text/javascript;base64," + Buffer.from(code).toString("base64");
  compiled.set(url.href, result); return result;
}
const { PreferencesProvider, usePreferences } = await import(await jsxModule(new URL("../src/settings/PreferencesProvider.jsx", import.meta.url)));
const { default: SettingsShell } = await import(await jsxModule(new URL("../src/pages/SettingsShell.jsx", import.meta.url)));
const { default: OpalSidebar } = await import(await jsxModule(new URL("../src/components/workspace/OpalSidebar.jsx", import.meta.url)));
const auth = { demoMode: true, status: "demo", user: { email: "synthetic@example.invalid", name: "Synthetic" }, canQuery: false };
test("actual provider-backed Settings renders without confusing the undo snapshot and callback", () => {
  const html = renderToStaticMarkup(React.createElement(PreferencesProvider, { auth, previewEnabled: true },
    React.createElement(SettingsShell, { auth, onBack() {}, onNavigate() {} })));
  assert.match(html, /id="settings-heading"/); assert.match(html, /data-settings-category="privacy"/);
  assert.match(html, /synthetic@example.invalid/); assert.match(html, /No unsaved preference changes/);
  assert.doesNotMatch(html, />Undo /); assert.match(html, /id="settings-field-theme"/);
});
test("provider context keeps absent undo data distinct from its callable draft operation", () => {
  function Probe() {
    const preferences = usePreferences();
    assert.equal(preferences.undo, null); assert.equal(typeof preferences.undoDraft, "function");
    assert.equal(typeof preferences.persistDeviceValue, "function");
    return React.createElement("p", null, preferences.effective.account.accent);
  }
  assert.match(renderToStaticMarkup(React.createElement(PreferencesProvider, { auth }, React.createElement(Probe))), /pearl/);
});
function sidebar(sections) {
  const chat = { durable: true, faqs: [{ id: "starter", title: "Starter title", prompt: "Synthetic starter" }],
    drafts: [{ id: "draft", title: "Unsent" }], conversations: [{ id: "recent", title: "Saved title", messageCount: 1 }],
    filters: { search: "", archived: false, projectId: null }, chats: { loading: false }, activeConversationId: "draft",
    prompts: { items: [{ id: "prompt", label: "Saved prompt title", prompt: "Synthetic saved prompt" }], loading: false },
    projects: { items: [{ id: "project", name: "Project title" }], loading: false } };
  return renderToStaticMarkup(React.createElement(OpalSidebar, { chat, auth, preferences: { sidebar_sections: sections, recents_count: 10 },
    onNewChat() {}, onSelect() {}, onPrompt() {}, onNavigate() {}, onClose() {} }));
}
const headings = (html) => [...html.matchAll(/<h2[^>]*>([\s\S]*?)<\/h2>/g)].map((match) => match[1].replace(/<[^>]+>/g, ""));
test("actual sidebar DOM reading and keyboard sequence follow saved optional section order", () => {
  const variants = [
    [["projects", "recents", "prompts"], ["Drafts in this visit", "Projects", "Recent chats", "Starter questions", "Saved prompts"]],
    [["prompts", "projects", "recents"], ["Drafts in this visit", "Starter questions", "Saved prompts", "Projects", "Recent chats"]],
    [["recents", "prompts", "projects"], ["Drafts in this visit", "Recent chats", "Starter questions", "Saved prompts", "Projects"]]
  ];
  for (const [order, expected] of variants) {
    const html = sidebar(order); assert.deepEqual(headings(html), expected);
    assert.doesNotMatch(html, /style="order:/); assert.doesNotMatch(html, /tabindex="[1-9]/);
  }
});
test("hiding optional sidebar sections retains unsent drafts, New Chat and account access", () => {
  const html = sidebar([]); assert.deepEqual(headings(html), ["Drafts in this visit"]);
  assert.match(html, /New chat/); assert.match(html, /aria-label="Account menu"/); assert.match(html, /Draft · Unsent/);
  assert.doesNotMatch(html, /Private projects|Private saved prompts|Starter title|Saved title/);
  assert.deepEqual(headings(sidebar(["projects"])), ["Drafts in this visit", "Projects"]);
});
