import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";
import { resultFixture } from "./result-companion-fixture.mjs";
import { decodeResultBrief } from "../src/features/resultCompanion/contract.js";
import { resultFollowupFields } from "../src/features/resultCompanion/followup.js";
import { prepareGuidedQuestion } from "../src/services/guidedQuestion.js";

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
const { ResultCompanionContent } = await import(await jsxModule(new URL("../src/features/resultCompanion/ResultCompanionDialog.jsx", import.meta.url)));
const { default: AquaMessage } = await import(await jsxModule(new URL("../src/components/chat/AquaMessage.jsx", import.meta.url)));
function render(options = {}, extra = {}) {
  const f = resultFixture(options), reply = decodeResultBrief(f.reply, f.binding, 0);
  return renderToStaticMarkup(React.createElement(ResultCompanionContent, { binding: f.binding,
    state: { phase: reply.brief.status, columnIndex: 0, reply, error: "", ticket: 1 }, ...extra }));
}

test("message adds one contextual action only for complete durable owned results without replacing their table", () => {
  const f = resultFixture(), draw = message => renderToStaticMarkup(React.createElement(AquaMessage, { message, onUnderstandResult() {} }));
  const html = draw(f.message);
  assert.equal((html.match(/data-understand-result/g) || []).length, 1); assert.match(html, /Understand this result/); assert.match(html, /<table/); assert.match(html, /Copy response/);
  for (const change of [{ status: "pending" }, { historical: false }, { resultUnavailable: true }]) assert.doesNotMatch(draw({ ...f.message, ...change }), /data-understand-result/);
  assert.doesNotMatch(renderToStaticMarkup(React.createElement(AquaMessage, { message: f.message })), /data-understand-result/);
});

test("facts show exact original-order row references, full tie counts and honest units/source limits", () => {
  const html = render();
  assert.match(html, /9007199254740993\.01/); assert.match(html, /-0\.0000000001/); assert.match(html, /Saved row 2, field 1/); assert.match(html, /Saved row 4, field 1/);
  assert.match(html, /2 returned rows have this value/); assert.match(html, /Unit unspecified/); assert.match(html, /Source freshness/); assert.match(html, /generation time is not source freshness/);
  assert.match(html, /before table sorting or paging/); assert.match(html, /<label for=/); assert.match(html, /data-result-column/);
  assert.doesNotMatch(html, /\$9,007|USD|portfolio leader|forecast|Approve|Send payment/);
});

test("empty and legacy results have explicit non-comparison states while failures reveal no prior figures", () => {
  assert.match(render({ empty: true }), /This query returned no rows/); assert.match(render({ empty: true }), /does not establish that the underlying activity never exists/);
  const legacy = render({ legacy: true }); assert.match(legacy, /older saved result/); assert.match(legacy, /Numerical comparisons are unavailable/); assert.doesNotMatch(legacy, /Lowest saved|Highest saved/);
  for (const phase of ["unavailable", "denied", "stale", "error"]) {
    const html = render({}, { state: { phase, columnIndex: 0, reply: null, error: "Fixed safe failure", ticket: 2 } });
    assert.match(html, /role="alert"/); assert.match(html, /Retry saved-field check/); assert.doesNotMatch(html, /9007199254740993\.01|data-result-facts/);
  }
  const loading = render({}, { state: { phase: "loading", columnIndex: 1, reply: null, error: "", ticket: 2 } });
  assert.match(loading, /role="status"/); assert.doesNotMatch(loading, /data-result-facts/);
});

test("follow-up reuses editable guide fields and explicit prepare/apply without a submitting form", () => {
  const fields = resultFollowupFields("missing_values", "Sample value"), draft = prepareGuidedQuestion(fields).question;
  const guide = { fields, draft, dirty: true, edited: false, ticket: 1, error: null, conflict: false };
  const html = render({}, { guide });
  assert.match(html, /data-companion-guide-prepare/); assert.match(html, /data-result-draft/); assert.match(html, /Grouping: Not specified/);
  assert.match(html.match(/<button[^>]*data-result-apply[^>]*>/)?.[0] || "", /disabled/); assert.doesNotMatch(html, /<form|type="submit"/);
  assert.match(html, /not anchored to this saved answer/); assert.match(html, /Nothing is sent/);
  const edited = render({}, { guide: { ...guide, dirty: false, edited: true, draft: "My explicit edited question" } });
  assert.match(edited, /Your edited draft is what will be applied/);
  const conflict = render({}, { guide: { ...guide, dirty: false, conflict: true } }); assert.match(conflict, /text was preserved/);
  const readonly = render({}, { guide: { ...guide, dirty: false }, canApply: false }); assert.match(readonly, /active, unarchived chat/);
});

test("hostile question and field labels are literal text, never markup or links", () => {
  const f = resultFixture(), hostile = '<img src=x onerror="bad()">';
  f.binding.question = hostile; f.reply.brief.question = hostile;
  f.binding.table.columns[0].label = hostile; f.reply.brief.field.label = hostile;
  const reply = decodeResultBrief(f.reply, f.binding, 0);
  const html = renderToStaticMarkup(React.createElement(ResultCompanionContent, { binding: f.binding, state: { phase: "ready", columnIndex: 0, reply, error: "", ticket: 1 } }));
  assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img|<script|<a\s/);
});
