import assert from "node:assert/strict";
import test from "node:test";
import { quickSwitchItems, workspaceShortcut } from "../src/components/workspace/quickSwitchPolicy.js";
import { chatSearchPresentation } from "../src/components/workspace/chatSearchPresentation.js";

test("quick switch deduplicates recovery before saved chats and never searches message or draft bodies", () => {
  const draft = { id: "draft", title: "Café revenue", draft: "secret-needle" };
  const chat = { durable: true, recoverableDrafts: [draft], conversations: [
    { ...draft, messageCount: 2, messages: [{ content: "secret-needle" }] },
    { id: "saved", title: "Monthly costs", messageCount: 2 }, { id: "empty", title: "Empty", messageCount: 0 },
  ] };
  const before = structuredClone(chat);
  assert.equal(quickSwitchItems(chat).filter((item) => item.kind === "chat").length, 2);
  assert.equal(quickSwitchItems(chat, "CAFE revenue")[0].item, draft);
  assert.deepEqual(quickSwitchItems(chat, "secret-needle"), []);
  assert.deepEqual(quickSwitchItems(chat, "empty"), []);
  assert.deepEqual(chat, before);
});

test("navigation remains bounded and filtering happens before the result cap", () => {
  const chat = { durable: true, conversations: Array.from({ length: 100 }, (_, i) => ({ id: String(i), title: `Report ${i}`, messageCount: 1 })) };
  assert.equal(quickSwitchItems(chat).length, 20);
  assert.equal(quickSwitchItems(chat, "Report 99")[0].item.id, "99");
  assert.equal(quickSwitchItems({}).length, 4);
  assert.equal(quickSwitchItems({}, "Search saved chats")[0].id, "search");
});

test("switcher indexes only the current owner input and uses titles as literal data", () => {
  const title = '<img src=x onerror="alert(1)">';
  assert.equal(quickSwitchItems({ conversations: [{ id: "one", title, messages: [{}] }] }, "img")[0].label, title);
  assert.deepEqual(quickSwitchItems({ conversations: [] }, "img"), []);
});

const key = (overrides = {}) => ({ key: "k", ctrlKey: true, target: { closest: () => null }, ...overrides });
test("shortcuts work across platforms and never override composition, modal or hidden surfaces", () => {
  assert.equal(workspaceShortcut(key()), "switch");
  assert.equal(workspaceShortcut(key({ ctrlKey: false, metaKey: true, key: "K" })), "switch");
  for (const overrides of [{ isComposing: true }, { keyCode: 229 }, { repeat: true }, { defaultPrevented: true }, { altKey: true }, { shiftKey: true }]) {
    assert.equal(workspaceShortcut(key(overrides)), null);
  }
  assert.equal(workspaceShortcut(key(), { modalOpen: true }), null);
  assert.equal(workspaceShortcut(key(), { hidden: true }), null);
});

test("slash focuses the composer only outside editable text and without modifiers", () => {
  const slash = key({ key: "/", ctrlKey: false });
  assert.equal(workspaceShortcut(slash), "composer");
  assert.equal(workspaceShortcut({ ...slash, target: { closest: () => ({ tagName: "TEXTAREA" }) } }), null);
  assert.equal(workspaceShortcut({ ...slash, metaKey: true }), null);
  assert.equal(workspaceShortcut({ ...slash, shiftKey: true }), null);
});

const filters = { search: "new", archived: false, projectId: null };
const oldPage = { durable: true, filters, conversations: [{ id: "old", title: "Old result", messageCount: 1 }],
  chats: { criteria: { ...filters, search: "old" }, loading: false } };
test("filter changes hide old matches even before the new read effect starts", () => {
  const result = chatSearchPresentation(oldPage);
  assert.equal(result.loading, true); assert.deepEqual(result.matches, []);
  assert.match(result.status, /Loading/);
});

test("a failed read cannot present a stale page as a successful empty search", () => {
  const result = chatSearchPresentation({ ...oldPage, chats: { ...oldPage.chats, error: true } });
  assert.equal(result.loading, false); assert.equal(result.failed, true);
  assert.deepEqual(result.matches, []); assert.match(result.status, /could not load/);
  assert.doesNotMatch(result.status, /0 chats match/);
});

test("successful, loading, empty and visit-local search stay distinct", () => {
  const good = { ...oldPage, chats: { criteria: filters, loading: false } };
  assert.equal(chatSearchPresentation(good).matches.length, 1);
  assert.match(chatSearchPresentation({ ...good, conversations: [] }).status, /0 chats match/);
  assert.equal(chatSearchPresentation({ ...good, chats: { loading: true } }).matches.length, 0);
  const demo = { conversations: [{ title: "Costs", messages: [{}] }, { title: "Sales", messages: [{}] }, { title: "Empty", messages: [] }] };
  assert.equal(chatSearchPresentation(demo, "cost").matches.length, 1);
});
