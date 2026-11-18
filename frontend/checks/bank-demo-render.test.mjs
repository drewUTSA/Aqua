import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";
import { contextEnvelope, reportEnvelope, ownerId, option } from "./bank-demo-fixture.mjs";
import { decodeBankContext, decodeBankReport } from "../src/features/bankDemo/contract.js";

async function jsxModule(url) {
  const transformed = await transform(await readFile(url, "utf8"), { sourcefile: url.pathname, loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const name = match[1]; imports.set(name, name === "react" ? import.meta.resolve(name) : name.endsWith(".jsx") ? await jsxModule(new URL(name, url)) : new URL(name, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, name) => `from ${JSON.stringify(imports.get(name))}`);
  return "data:text/javascript;base64," + Buffer.from(code).toString("base64");
}
const { BankDemoContent } = await import(await jsxModule(new URL("../src/features/bankDemo/BankDemoPanel.jsx", import.meta.url)));
const context = decodeBankContext(contextEnvelope(), ownerId);
const render = state => renderToStaticMarkup(React.createElement(BankDemoContent, { state }));

test("loading, unavailable, denied, source-change and empty scope have distinct honest states", () => {
  const loading = render({ phase: "loading" }); assert.match(loading, /role="status"/); assert.match(loading, /aria-hidden="true"/); assert.doesNotMatch(loading, /<table/);
  for (const [phase, error] of [["unavailable", "Demo is not enabled."], ["denied", "Outside this scope."], ["stale", "Source changed."], ["error", "Read failed."]]) {
    const html = render({ phase, error }); assert.match(html, /role="alert"/); assert.ok(html.includes(error)); assert.match(html, /Check demo availability/); assert.doesNotMatch(html, /<table/);
  }
  const empty = render({ phase: "empty", context: { ...context, persona: "none", reports: [] } });
  assert.match(empty, /No fictional reports are assigned/); assert.match(empty, /app role does not grant bank access/); assert.doesNotMatch(empty, /<select|data-bank-read/);
});

test("picker lists only supplied reports, has visible label and requires explicit read without action tools", () => {
  const html = render({ phase: "ready", context, selected: "" });
  assert.match(html, /<label for=/); assert.match(html, /data-bank-report-picker/); assert.match(html, /Read fictional report/);
  assert.match(html.match(/<button[^>]*data-bank-read[^>]*>/)?.[0] || "", /disabled=""/);
  assert.match(html, /Server-configured demo scope/); assert.match(html, /fictional scope, not bank identity/);
  assert.doesNotMatch(html, /value="manager"|value="audit_issue_summary"|Apply to composer|data-companion-apply|Approve|Send payment/);
});

test("report cells preserve exact text and safely render original citation, limits and inert suggestions", () => {
  const wire = reportEnvelope(); wire.result.rows[0][2] = "9007199254740993.01";
  wire.result.procedure.text = '<img src=x onerror="bad()"> [link](javascript:bad())';
  const result = decodeBankReport(wire, ownerId, option.id, context);
  const html = render({ phase: "ready", context, selected: option.id, result });
  assert.match(html, /<caption>Exact fictional aggregates/); assert.equal((html.match(/scope="col"/g) || []).length, 3);
  assert.match(html, />9007199254740993\.01<\/td>/); assert.match(html, /Closing balance \(USD\)/); assert.match(html, /Accounts \(count\)/);
  assert.match(html, /Fictional · Partial period/); assert.match(html, /2026-11-01/); assert.match(html, /2026-11-16/);
  assert.match(html, /tabindex="0" role="region"/i); assert.match(html, /<summary>Cited fictional procedure and human next steps/);
  assert.match(html, /deposit_help/); assert.match(html, /fictional-demo-v1/); assert.match(html, /No approval has been recorded/);
  assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img|<script|<a\s|dangerouslySetInnerHTML/);
});
