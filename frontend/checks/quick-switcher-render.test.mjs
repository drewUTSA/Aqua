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
    const name = match[1];
    imports.set(name, name === "react" ? import.meta.resolve(name) : name.endsWith(".jsx")
      ? await jsxModule(new URL(name, url)) : new URL(name, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, name) => `from ${JSON.stringify(imports.get(name))}`);
  return "data:text/javascript;base64," + Buffer.from(code).toString("base64");
}
const { default: QuickSwitcher } = await import(await jsxModule(new URL("../src/components/workspace/QuickSwitcher.jsx", import.meta.url)));
const { SidebarSearchDialog } = await import(await jsxModule(new URL("../src/components/workspace/SidebarRecentsDialogs.jsx", import.meta.url)));

test("real switcher escapes hostile titles, labels scope and never renders or submits draft bodies", () => {
  let calls = 0;
  const html = renderToStaticMarkup(React.createElement(QuickSwitcher, {
    chat: { durable: true, recoverableDrafts: [{ id: "draft", title: "<img src=x onerror=alert(1)>", draft: "PRIVATE-BODY" }] },
    onSelect() { calls++; }, onAction() { calls++; }, onClose() { calls++; },
  }));
  assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<img|PRIVATE-BODY/);
  assert.match(html, /<dialog/); assert.match(html, /aria-labelledby=/);
  assert.match(html, /role="status"/); assert.match(html, /Searches loaded titles in this account/);
  assert.match(html, /maxLength="120"/i); assert.equal(calls, 0);
});

test("demo switcher does not claim server search or account persistence", () => {
  const html = renderToStaticMarkup(React.createElement(QuickSwitcher, { chat: {} }));
  assert.match(html, /Search titles in this visit/); assert.match(html, /not saved to an account/);
  assert.doesNotMatch(html, /Search titles on the server/);
});

test("actual search dialog hides failed stale results and their pagination", () => {
  const chat = { durable: true, filters: { search: "new" }, chats: { error: true, cursor: "old-page" },
    conversations: [{ id: "old", title: "STALE-TITLE", messageCount: 1 }] };
  const html = renderToStaticMarkup(React.createElement(SidebarSearchDialog, { chat }));
  assert.match(html, /could not load/); assert.doesNotMatch(html, /STALE-TITLE|More matching chats|0 chats match/);
});
