import assert from "node:assert/strict";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFile } from "node:fs/promises";
import { transformWithEsbuild } from "vite";
import { initialContextNotesState } from "../src/features/contextNotes/state.js";
import { createCompanionToolsController } from "../src/hooks/companionToolsState.js";
import { library, readReply, prepared, item, fields } from "./context-notes-fixture.mjs";

async function jsxModule(url) {
  const transformed = await transformWithEsbuild(await readFile(url, "utf8"), url.pathname, { loader: "jsx", format: "esm" });
  let code = transformed.code.replace(/import\s+["'][^"']+\.css["'];?/g, ""); const imports = new Map();
  for (const match of code.matchAll(/from\s+["']([^"']+)["']/g)) {
    const name = match[1]; imports.set(name, name === "react" ? import.meta.resolve(name) : name.endsWith(".jsx") ? await jsxModule(new URL(name, url)) : new URL(name, url).href);
  }
  code = code.replace(/from\s+["']([^"']+)["']/g, (_, name) => `from ${JSON.stringify(imports.get(name))}`);
  return "data:text/javascript;base64," + Buffer.from(code).toString("base64");
}
const { ContextNotesContent } = await import(await jsxModule(new URL("../src/features/contextNotes/ContextNotesPanel.jsx", import.meta.url)));
const { clearHeldCompanionReply } = await import(await jsxModule(new URL("../src/components/workspace/CompanionToolsDialog.jsx", import.meta.url)));
const render = (state, canQuery = true) => renderToStaticMarkup(React.createElement(ContextNotesContent, { state: { ...initialContextNotesState(), ...state }, canQuery }));
const loaded = () => ({ phase: "ready", library: library(), selected: item(), note: readReply().note, editor: fields() });

test("loading, disabled, error and empty states remain honest and leave close/recovery to the host", () => {
  assert.match(render({ phase: "loading" }), /role="status"[^>]*>Reading your saved-note list/);
  const blocked = render({ phase: "blocked", error: "Reload before continuing." });
  assert.match(blocked, /role="alert"/); assert.match(blocked, /Check saved notes availability/); assert.doesNotMatch(blocked, /data-notes-body|data-notes-apply/);
  const empty = library(); empty.items = []; const html = render({ phase: "ready", library: empty });
  assert.match(html, /No notes saved yet/); assert.match(html, /New saved note/); assert.doesNotMatch(html, /data-notes-body/);
});

test("metadata list cannot leak bodies; unavailable entries have a generic forget-only path without grant", () => {
  const current = library(); current.scope.can_use = false; current.items = [current.items[1]];
  const html = render({ phase: "ready", library: current, selected: current.items[0] }, false);
  assert.match(html, /Unavailable saved context — forget only/); assert.match(html, /data-notes-forget/);
  assert.match(html.match(/<button[^>]*data-notes-new[^>]*>/)?.[0] || "", /disabled=""/);
  assert.doesNotMatch(html, /My team definition|completed task|data-notes-body|data-notes-apply/);
});

test("editor has visible labels, separate Unicode counters and explicit correction/forget actions", () => {
  const state = loaded(); state.editor = { ...state.editor, label: "😀", body: "😀\n" };
  const html = render(state); assert.equal((html.match(/<label for=/g) || []).length, 3);
  assert.match(html, /1\/120 characters · 4\/512 bytes/); assert.match(html, /3\/2000 text units · 5\/2048 bytes/);
  assert.match(html, /Save correction/); assert.match(html, /Save the correction before preparing/);
  assert.match(html.match(/<button[^>]*data-notes-prepare[^>]*>/)?.[0] || "", /disabled=""/);
  const confirmation = render({ ...loaded(), confirmingForget: true }); assert.match(confirmation, /Copies you already sent remain in chat history/);
  assert.match(confirmation, /Forget saved entry/); assert.match(confirmation, /Keep entry/);
});

test("reviewed draft is inert plain text with explicit Apply and provider/history disclosure", () => {
  const state = { ...loaded(), prepared: prepared(), draft: '<img src=x onerror="bad()">' };
  const html = render(state); assert.match(html, /User-saved, unverified source/); assert.match(html, /Editable draft/);
  assert.match(html, /Apply to composer draft/); assert.match(html, /nothing is sent/); assert.match(html, /configured model or provider/);
  assert.match(html, /Forgetting the note does not remove that copy/); assert.match(html, /&lt;img/);
  assert.doesNotMatch(html, /<img|<script|<a\s|dangerouslySetInnerHTML|>Send<|Approve|Execute/);
});

test("switching areas preserves the pending help menu but cancels a held help answer", async () => {
  let menuReply, helpReply;
  const controller = createCompanionToolsController({ api: { menu: () => new Promise(resolve => { menuReply = resolve; }), help: () => new Promise(resolve => { helpReply = resolve; }) },
    options: {}, assertCurrent() {}, onState() {} });
  const tools = () => ({ state: controller.snapshot(), edit: controller.edit });
  const lookup = controller.load(); clearHeldCompanionReply(tools()); menuReply({ capabilities: [] }); await lookup;
  assert.equal(controller.snapshot().phase, "ready"); assert.notEqual(controller.snapshot().menu, null);
  const reading = controller.ask("Aqua help"); clearHeldCompanionReply(tools());
  helpReply({ status: "matched", message: "OLD_HELD_REPLY" }); await reading;
  assert.equal(controller.snapshot().phase, "ready"); assert.equal(controller.snapshot().answer, null);
});
