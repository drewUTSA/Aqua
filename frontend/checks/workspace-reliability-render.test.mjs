import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transform } from "esbuild";

const compiled = new Map();
async function jsxModule(url) {
  if (compiled.has(url.href)) return compiled.get(url.href);
  const transformed = await transform(await readFile(url, "utf8"), { sourcefile: url.pathname, loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, "");
  const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const name = match[1];
    imports.set(name, name === "react" ? import.meta.resolve(name) : name.endsWith(".jsx")
      ? await jsxModule(new URL(name, url)) : new URL(name, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, name) => `from ${JSON.stringify(imports.get(name))}`);
  const result = "data:text/javascript;base64," + Buffer.from(code).toString("base64");
  compiled.set(url.href, result); return result;
}
const { default: WorkspaceLibrary } = await import(await jsxModule(new URL("../src/components/workspace/WorkspaceLibrary.jsx", import.meta.url)));
const { default: SidebarProjects } = await import(await jsxModule(new URL("../src/components/workspace/SidebarProjects.jsx", import.meta.url)));
const { default: Boundary } = await import(await jsxModule(new URL("../src/components/workspace/QuickSwitcherBoundary.jsx", import.meta.url)));
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const page = (changes = {}) => ({ items: [], loading: false, cursor: null, ...changes });
const chat = (kind, changes) => ({ durable: true, busy: false, filters: {}, prompts: page(), projects: page(),
  [kind]: page(changes), retryPrompts() {}, retryProjects() {} });

test("failed first prompt read shows local retry rather than claiming an empty account", () => {
  const html = render(WorkspaceLibrary, { section: "prompts", chat: chat("prompts", { error: true }) });
  assert.match(html, /role="alert"/); assert.match(html, /Saved prompts could not be loaded/);
  assert.match(html, /Retry saved prompts/); assert.doesNotMatch(html, /No saved prompts yet/);
  assert.match(render(WorkspaceLibrary, { section: "prompts", chat: chat("prompts", {}) }), /No saved prompts yet/);
});

test("failed prompt pagination retains labeled stale items without stale pagination or a success claim", () => {
  const html = render(WorkspaceLibrary, { section: "prompts", chat: chat("prompts", { error: true,
    cursor: "OLD_PAGE", fromCursor: "OLDER_PAGE", items: [{ id: "p", label: "Previously loaded", prompt: "Synthetic" }] }) });
  assert.match(html, /Previously loaded/); assert.match(html, /may be out of date/);
  assert.doesNotMatch(html, /More saved prompts|First saved prompts|No saved prompts yet|OLD_PAGE/);
});

test("both project surfaces distinguish a failed read, retained stale projects and a successful empty list", () => {
  for (const items of [[], [{ id: "p", name: "Previously loaded project" }]]) {
    const value = chat("projects", { error: true, items, cursor: "OLD_PAGE" });
    const variants = [render(WorkspaceLibrary, { section: "projects", chat: value }),
      render(SidebarProjects, { chat: value, projectChats: { projectId: null } })];
    for (const html of variants) {
      assert.match(html, /Projects could not be loaded/); assert.match(html, /Retry projects/);
      assert.doesNotMatch(html, /No projects yet|More projects/);
      if (items.length) assert.match(html, /may be out of date/);
    }
  }
  assert.match(render(SidebarProjects, { chat: chat("projects", {}), projectChats: {} }), /No projects yet/);
});

test("optional view failure text is local and cannot serialize raw errors or account data", () => {
  for (const kind of ["settings", "prompts", undefined]) {
    const boundary = new Boundary({ kind, onClose() {}, children: React.createElement("p", null, "PRIVATE_CHILD") });
    boundary.state = Boundary.getDerivedStateFromError(new Error("PRIVATE_EXCEPTION"));
    const html = renderToStaticMarkup(boundary.render());
    assert.match(html, /unavailable|could not open/); assert.match(html, /<button/);
    assert.doesNotMatch(html, /PRIVATE_CHILD|PRIVATE_EXCEPTION|Reload|Try again/);
  }
});
