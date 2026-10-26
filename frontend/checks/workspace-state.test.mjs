import assert from "node:assert/strict";
import test from "node:test";
import { initialWorkspace, failSubmission, finishHistory, finishSubmission, maskSavedResults, mergeMessages, openConversation, changeRecord, removeConversation } from "../src/hooks/workspaceState.js";

test("new local draft has no server record and navigation preserves distinct unsent text", () => {
  const initial = initialWorkspace(), first = initial.activeId;
  const drafted = changeRecord(initial, first, (item) => ({ ...item, draft: "Private unsent draft" }));
  const opened = openConversation(drafted, { id: "owned-chat", title: "Saved", messageCount: 2 });
  assert.equal(opened.records[first].draft, "Private unsent draft"); assert.equal(opened.records["owned-chat"].draft, "");
  assert.equal(opened.activeId, "owned-chat"); assert.equal(initial.records[first].revision, null);
});
test("canonical submission reconciles first chat without duplicating optimistic input", () => {
  const state = initialWorkspace(), id = state.activeId;
  state.records[id] = { ...state.records[id], draft: "Typed during request", operation: { clientId: "operation" }, messages: [{ id: "local", role: "user", optimisticOperation: "operation" }] };
  const result = { chat: { id: "server-chat", revision: 1 }, request: { state: "complete" }, input: { id: "input", role: "user", sequence: 1 }, assistant: { id: "reply", role: "aqua", sequence: 2 } };
  const next = finishSubmission(state, id, "operation", result);
  assert.equal(next.activeId, "server-chat"); assert.equal(next.records[id], undefined);
  assert.deepEqual(next.records["server-chat"].messages.map((message) => message.id), ["input", "reply"]);
  assert.equal(next.records["server-chat"].draft, "Typed during request"); assert.equal(next.records["server-chat"].operation, null);
});
test("stale or removed operation cannot repopulate another selected account/chat", () => {
  const state = initialWorkspace(), snapshot = JSON.stringify(state);
  const result = { chat: { id: "foreign" }, request: { state: "complete" } };
  assert.equal(finishSubmission(state, "missing", "stale", result), state);
  assert.equal(finishSubmission(state, state.activeId, "stale", result), state); assert.equal(JSON.stringify(state), snapshot);
});
test("saved failure recovers its prompt without replacing a newer draft", () => {
  const state = initialWorkspace(), id = state.activeId;
  state.records[id].operation = { clientId: "op", prompt: "Recover this prompt" };
  const result = { chat: { id: "saved" }, request: { state: "error" }, input: { id: "input", sequence: 1 }, assistant: { id: "reply", sequence: 2, response: { status: "error" } } };
  assert.equal(finishSubmission(state, id, "op", result).records.saved.draft, "Recover this prompt");
  state.records[id].draft = "Newer draft";
  assert.equal(finishSubmission(state, id, "op", result).records.saved.draft, "Newer draft");
});
test("stable sequence merge deduplicates retry input and bounds retained history", () => {
  const messages = Array.from({ length: 240 }, (_, index) => ({ id: `m${index}`, sequence: index + 1 }));
  const merged = mergeMessages(messages.slice(30), messages.slice(0, 40));
  assert.equal(merged.length, 200); assert.equal(new Set(merged.map((message) => message.id)).size, 200);
  assert.ok(merged.every((message, index) => !index || message.sequence > merged[index - 1].sequence));
});
test("definitively rejected submission restores the draft without fabricating saved input", () => {
  const state = initialWorkspace(), id = state.activeId, operation = { clientId: "op", prompt: "Rejected input" };
  state.records[id] = { ...state.records[id], operation, messages: [{ id: "saved", sequence: 1 }, { id: "local", role: "user", optimisticOperation: "op" }] };
  const rejected = failSubmission(state, id, operation, false).records[id];
  assert.equal(rejected.operation, null); assert.equal(rejected.draft, "Rejected input"); assert.deepEqual(rejected.messages.map((item) => item.id), ["saved"]);
  const uncertain = failSubmission(state, id, operation, true).records[id];
  assert.equal(uncertain.operation.clientId, "op"); assert.equal(uncertain.operation.uncertain, true); assert.equal(uncertain.messages.length, 2);
  state.records[id].draft = "Newer unsent input";
  assert.equal(failSubmission(state, id, operation, false).records[id].draft, "Newer unsent input");
});
test("late authorized history and submission responses cannot restore results after grant loss", async () => {
  const state = initialWorkspace(), id = state.activeId;
  state.records[id].operation = { clientId: "op", prompt: "Owned question" }; state.records[id].draft = "Keep this private draft";
  const input = { id: "input", role: "user", content: "Owned question", sequence: 1 }, assistant = { id: "reply", role: "aqua", content: "SECRET_RESULT",
    sequence: 2, response: { status: "success", sql: "SELECT SECRET_SQL", tables: [{ rows: [["SECRET_ROW"]] }] } };
  let grant = true, release; const delayed = new Promise((resolve) => { release = resolve; });
  const lateHistory = delayed.then(() => finishHistory(state, id, { items: [input, assistant], cursor: null }, false, grant));
  const lateSubmission = delayed.then(() => finishSubmission(state, id, "op", { chat: { id: "saved" }, request: { state: "complete" }, input, assistant }, grant));
  grant = false; release();
  for (const committed of [await lateHistory, await lateSubmission]) {
    assert.equal(JSON.stringify(committed).includes("SECRET"), false);
    const record = Object.values(committed.records)[0]; assert.equal(record.draft, "Keep this private draft");
    assert.equal(record.messages[0].content, "Owned question"); assert.equal(record.messages[1].response.error.code, "access_denied");
  }
  assert.equal(maskSavedResults([assistant], true)[0].response.sql, "SELECT SECRET_SQL");
  assert.equal(JSON.stringify(maskSavedResults([assistant], false)).includes("SECRET"), false);
});
test("late first-submit remapping preserves a separately opened canonical chat and both drafts", () => {
  const state = initialWorkspace(), source = state.activeId;
  state.records[source] = { ...state.records[source], draft: "Source text typed during first request", operation: { clientId: "first" },
    messages: [{ id: "optimistic-first", role: "user", optimisticOperation: "first" }] };
  const selected = openConversation(state, { id: "canonical", revision: 2, title: "Newer renamed title", messageCount: 4 });
  selected.records.canonical.draft = "Newer canonical chat draft";
  selected.records.canonical.operation = { clientId: "second", busy: true };
  selected.records.canonical.messages = [{ id: "new-input", role: "user", optimisticOperation: "second" }];
  const result = { chat: { id: "canonical", revision: 1, title: "Original title", messageCount: 2 }, request: { state: "complete" },
    input: { id: "first-input", role: "user", sequence: 1 }, assistant: { id: "first-reply", role: "aqua", sequence: 2 } };
  const next = finishSubmission(selected, source, "first", result);
  assert.equal(next.activeId, "canonical"); assert.equal(next.records.canonical.draft, "Newer canonical chat draft");
  assert.equal(next.records.canonical.operation.clientId, "second"); assert.equal(next.records.canonical.title, "Newer renamed title");
  assert.deepEqual(next.records.canonical.messages.map((item) => item.id), ["first-input", "first-reply", "new-input"]);
  assert.equal(next.records[source].draft, "Source text typed during first request"); assert.equal(next.records[source].operation, null);
  assert.equal(next.records[source].messages.length, 0);
  const pending = finishSubmission(selected, source, "first", { ...result, request: { state: "pending" } });
  assert.equal(pending.records.canonical.operation.clientId, "second"); assert.equal(pending.records.canonical.draft, "Newer canonical chat draft");
  assert.equal(pending.records[source].operation.clientId, "first"); assert.equal(pending.records[source].operation.uncertain, true);
});
test("confirmed canonical deletion fences a held first-submit response without losing unsent source text", () => {
  const state = initialWorkspace(), source = state.activeId;
  state.records[source].operation = { clientId: "op", prompt: "Question for deleted chat" }; state.records[source].draft = "Newer unsent text";
  const opened = openConversation(state, { id: "deleted", title: "Canonical row", messageCount: 2 });
  const removed = removeConversation(opened, "deleted"), activeId = removed.activeId;
  const result = { chat: { id: "deleted" }, request: { state: "complete" }, input: { id: "input" },
    assistant: { id: "reply", role: "aqua", response: { sql: "DELETED_SECRET_SQL" } } };
  const late = finishSubmission(removed, source, "op", result);
  assert.equal(late.records.deleted, undefined); assert.equal(late.activeId, activeId);
  assert.equal(late.records[source].draft, "Newer unsent text"); assert.equal(late.records[source].operation, null);
  assert.equal(JSON.stringify(late).includes("DELETED_SECRET"), false);
  assert.equal(openConversation(late, { id: "deleted" }), late);
});
