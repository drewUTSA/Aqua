import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";

async function jsxModule(url) {
  const transformed = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname, { loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const name = match[1]; imports.set(name, name === "react" ? import.meta.resolve(name) : name.endsWith(".jsx") ? await jsxModule(new URL(name, url)) : new URL(name, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, name) => `from ${JSON.stringify(imports.get(name))}`);
  return "data:text/javascript;base64," + Buffer.from(code).toString("base64");
}
const { CompanionToolsContent, GuidedQuestionFields } = await import(await jsxModule(new URL("../src/components/workspace/CompanionToolsDialog.jsx", import.meta.url)));
const { default: Boundary, OptionalDialogLoading } = await import(await jsxModule(new URL("../src/components/workspace/QuickSwitcherBoundary.jsx", import.meta.url)));
const menu = { capabilities: [{ id: "app_help", behavior: "reviewed_lookup" }] };
const render = (state, extra = {}) => renderToStaticMarkup(React.createElement(CompanionToolsContent, { state, mode: "help", question: "", canQuery: false, ...extra }));

test("success renders plain reviewed text and citations without HTML, links or automatic actions", () => {
  const html = render({ phase: "answered", menu, answer: { status: "answered", method: "reviewed_lookup", message: "<img src=x onerror=alert(1)> [unsafe](javascript:alert(1))",
    citations: [{ id: "overview", title: "<script>bad</script>", revision: "a".repeat(64) }] } });
  assert.match(html, /Reviewed help lookup/); assert.match(html, /No model or data query/); assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img|<script|<a\s|dangerouslySetInnerHTML/); assert.match(html, /data-method="reviewed_lookup"/);
  assert.match(html, /Source: overview/); assert.match(html, /aria-pressed="true"/); assert.match(html, /<label for=/); assert.match(html, /maxLength="2000"/i);
  assert.match(html, /title="a{64}">Version: a{12}<\/span>/);
});

test("loading, disabled, denied capability, failure and abstention remain distinct", () => {
  assert.match(render({ phase: "loading", menu: null }), /role="status"/);
  const unavailable = render({ phase: "unavailable", menu: null, error: "Not available on this server." });
  assert.match(unavailable, /Not available on this server/); assert.match(unavailable, /Check availability/); assert.doesNotMatch(unavailable, /data-companion-apply/);
  const denied = render({ phase: "ready", menu }); assert.match(denied, /Ask data requires current dataset access/); assert.match(denied, /data-companion-mode="data"[^>]*disabled/);
  assert.match(render({ phase: "abstained", menu, answer: { status: "abstained", method: "reviewed_lookup", message: "No clear guide", citations: [] } }), /No clear guide found/);
  const data = render({ phase: "ready", menu: { capabilities: [...menu.capabilities, { id: "authorized_question", behavior: "seed_draft" }] } }, { mode: "data", canQuery: true });
  assert.match(data, /Nothing is sent/); assert.match(data, /type="button" data-companion-apply/);
});

test("optional loading and failure reuse the native labeled dialog with a working close action", () => {
  const loading = renderToStaticMarkup(React.createElement(OptionalDialogLoading, { title: "Aqua tools", onClose() {}, closeLabel: "Close Aqua tools" }));
  assert.match(loading, /<dialog/); assert.match(loading, /aria-labelledby=/); assert.match(loading, /Close Aqua tools/);
  const boundary = new Boundary({ title: "Aqua tools unavailable", message: "Keep using the composer.", closeLabel: "Close Aqua tools", onClose() {} });
  boundary.state = { failed: true }; const failed = renderToStaticMarkup(boundary.render());
  assert.match(failed, /Aqua tools unavailable/); assert.match(failed, /Keep using the composer/); assert.match(failed, /Close Aqua tools/);
});

test("guided preparation labels required and optional fields, keeps literal input and blocks stale unprepared apply", () => {
  const guide = { active: true, fields: { measure: '<img src=x onerror="bad()">', grouping: "", period: "", filters: "" }, dirty: true,
    error: { field: "measure", message: "Enter what you want to measure." } };
  const fields = renderToStaticMarkup(React.createElement(GuidedQuestionFields, { fields: guide.fields, error: guide.error }));
  assert.equal((fields.match(/<label for=/g) || []).length, 4); assert.match(fields, /measure\? \(required\)/i);
  assert.equal((fields.match(/\(optional\)/g) || []).length, 3); assert.equal((fields.match(/maxLength="400"/gi) || []).length, 4);
  assert.match(fields, /&lt;img/); assert.doesNotMatch(fields, /<img|<a\s|<script/); assert.match(fields, /aria-invalid="true"/);
  assert.match(fields, /role="alert"/); assert.match(fields, /has not checked these fields against your dataset/);
  const html = render({ phase: "ready", menu: { capabilities: [...menu.capabilities, { id: "authorized_question", behavior: "seed_draft" }] } },
    { mode: "data", question: "Existing review draft", canQuery: true, guide });
  assert.match(html, /data-companion-guide-mode="free"/); assert.match(html, /Guide me/); assert.match(html, /Prepare draft for review/);
  assert.match(html.match(/<button[^>]*data-companion-apply[^>]*>/)?.[0] || "", /disabled=""/); assert.match(html, /Existing review draft/);
});
