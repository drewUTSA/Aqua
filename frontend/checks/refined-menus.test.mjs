import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";
import { advertisedModels, matchMenuText, moveMenuIndex, placeMenu } from "../src/components/navigation/menuPolicy.js";

test("roving keys wrap enabled actions and skip the unavailable demo sign-out", () => {
  assert.equal(moveMenuIndex("ArrowUp", 0, [0, 1]), 1);
  assert.equal(moveMenuIndex("ArrowDown", 1, [0, 1]), 0);
  assert.equal(moveMenuIndex("Home", 1, [0, 1]), 0);
  assert.equal(moveMenuIndex("End", 0, [0, 1]), 1);
  assert.equal(moveMenuIndex("ArrowUp", 0, [0]), 0);
  assert.equal(moveMenuIndex("End", 0, [0]), 0);
  assert.equal(moveMenuIndex("ArrowDown", 99, [0, 2]), 0);
  assert.equal(moveMenuIndex("ArrowUp", 99, [0, 2]), 2);
  assert.equal(moveMenuIndex("Home", 0, []), -1);
});

test("model name typeahead handles repeat cycling without selecting or inventing an option", () => {
  const names = ["Gemini Flash", "Gemma", "Qwen", "Qwen small"];
  assert.equal(matchMenuText(names, "g", 0), 1);
  assert.equal(matchMenuText(names, "gg", 1), 0);
  assert.equal(matchMenuText(names, "qwen s", 0), 3);
  assert.equal(matchMenuText(names, "missing", 2), 2);
  assert.equal(matchMenuText(names, "", 2), 2);
});

test("only a bounded unambiguous advertised set supplies names and literal descriptions", () => {
  const models = [{ id: "provider-a", name: "Named by server", description: "<img src=foreign>" }, { id: "provider-b", name: "Other option" }];
  assert.deepEqual(advertisedModels(models), [{ ...models[0] }, { ...models[1], description: "" }]);
  for (const input of [null, {}, [{ id: "a", name: "A" }, { id: "a", name: "Spoof" }], [{ id: "a\n", name: "Bad" }],
    [{ id: "a", name: "" }], Array.from({ length: 33 }, (_, index) => ({ id: String(index), name: "Excess" }))]) {
    assert.deepEqual(advertisedModels(input), []);
  }
  const clean = advertisedModels([{ id: "gemini", name: "Server label", description: { capability: "invented" }, fast: true }]);
  assert.deepEqual(clean, [{ id: "gemini", name: "Server label", description: "" }]);
  clean[0].name = "Local change"; assert.equal(models[0].name, "Named by server");
});

test("floating menus stay within desktop, mobile, zoomed and keyboard viewport bounds", () => {
  for (const viewport of [{ left: 0, top: 0, width: 1440, height: 900 }, { left: 0, top: 0, width: 320, height: 568 },
    { left: 100, top: 150, width: 360, height: 300 }]) {
    for (const placement of ["above", "below"]) for (const anchor of [
      { left: viewport.left + 8, right: viewport.left + 52, top: viewport.top + 16, bottom: viewport.top + 60 },
      { left: viewport.left + viewport.width - 52, right: viewport.left + viewport.width - 8, top: viewport.top + viewport.height - 60, bottom: viewport.top + viewport.height - 16 }
    ]) {
      const value = placeMenu(anchor, 600, viewport, { placement, width: 340, align: "end" });
      assert.ok(value.left >= viewport.left + 12);
      assert.ok(value.left + value.width <= viewport.left + viewport.width - 12);
      assert.ok(value.top >= viewport.top + 12);
      assert.ok(value.top + Math.min(600, value.maxHeight) <= viewport.top + viewport.height - 12);
    }
  }
});

const compiled = new Map();
async function jsxModule(url) {
  if (compiled.has(url.href)) return compiled.get(url.href);
  const transformed = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname, { loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const replacements = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const specifier = match[1];
    replacements.set(specifier, specifier === "react" ? import.meta.resolve("react")
      : specifier.endsWith(".jsx") ? await jsxModule(new URL(specifier, url)) : new URL(specifier, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, specifier) => `from ${JSON.stringify(replacements.get(specifier))}`);
  const result = "data:text/javascript;base64," + Buffer.from(code).toString("base64"); compiled.set(url.href, result); return result;
}
const { default: AccountMenu } = await import(await jsxModule(new URL("../src/components/workspace/AccountMenu.jsx", import.meta.url)));
const { default: ModelSelector } = await import(await jsxModule(new URL("../src/components/navigation/ModelSelector.jsx", import.meta.url)));

test("closed account control has one named entry and performs no navigation or sign-out", () => {
  let actions = 0;
  const html = renderToStaticMarkup(React.createElement(AccountMenu, { auth: { status: "authenticated", user: { name: "Fixture" }, logout() { actions++; } }, onNavigate() { actions++; } }));
  assert.equal((html.match(/aria-label="Account menu"/g) || []).length, 1);
  assert.match(html, /aria-expanded="false"/); assert.doesNotMatch(html, /role="menu"|Sign out of AQUA/); assert.equal(actions, 0);
});

test("model chooser renders only the selected server label, with no calls or fabricated capability badges", () => {
  let changes = 0;
  const props = { models: [{ id: "gemini", name: "Server chosen label", description: "Literal metadata" }], selectedModelId: "gemini", onSelectModel() { changes++; } };
  const html = renderToStaticMarkup(React.createElement(ModelSelector, props));
  assert.match(html, /Server chosen label/); assert.match(html, /aria-haspopup="menu"/);
  assert.doesNotMatch(html, /Fastest|Smartest|Recommended|Best for|role="menu"/); assert.equal(changes, 0);
  const unavailable = renderToStaticMarkup(React.createElement(ModelSelector, { ...props, models: [] }));
  assert.match(unavailable, /Models unavailable/); assert.match(unavailable, /disabled=""/); assert.doesNotMatch(unavailable, /Server chosen label/);
});
