import assert from "node:assert/strict";
import test from "node:test";
import { acceptAnalysis, activeAnalysis, analysisRequests, progressAnalysis } from "../src/hooks/workspaceAnalysisState.js";
import { initialWorkspace, openConversation, removeConversation, finishSubmission } from "../src/hooks/workspaceState.js";
import { analysisSnapshot } from "../src/services/analysisProtocol.js";
import { analysisLabel, analysisConnectionLabel } from "../src/services/analysisPresentation.js";
import { REQUEST, CHAT, snapshot } from "./analysis-fixture.mjs";
const saved = (...args) => analysisSnapshot(snapshot(...args), REQUEST);
const initial = () => openConversation(initialWorkspace(), saved().chat);

test("accepted202 canonicalizes the draft, clears HTTP uncertainty and discovers one saved request", () => {
  const state = initialWorkspace(), source = state.activeId; state.records[source].operation = { clientId: REQUEST, prompt: "Owned fixture question", busy: true };
  const next = acceptAnalysis(finishSubmission(state, source, REQUEST, saved("queued", "queued", 1, 0)), saved("queued", "queued", 1, 0), true);
  assert.equal(next.activeId, CHAT); assert.equal(next.records[CHAT].operation, null); assert.deepEqual(analysisRequests(next), [{ id: REQUEST, chatId: CHAT }]);
  assert.equal(activeAnalysis(next.records[CHAT]).state, "queued");
});

test("saved pending messages rediscover status without a submission operation", () => {
  const state = initial(); state.records[CHAT].messages = [saved().input, saved().assistant];
  assert.equal(state.records[CHAT].operation, null); assert.equal(activeAnalysis(state.records[CHAT]).stage, "checking");
  assert.deepEqual(analysisRequests(state), [{ id: REQUEST, chatId: CHAT }]);
});

test("monotonic progress cannot reverse terminal state or commit a result from metadata", () => {
  const state = acceptAnalysis(initial(), saved(), true), update = { requestId: REQUEST, state: "running", stage: "executing", version: 3, sequence: 2 };
  const progress = progressAnalysis(state, update); assert.equal(activeAnalysis(progress.records[CHAT]).stage, "executing");
  assert.equal(progress.records[CHAT].messages.at(-1).status, "pending");
  assert.equal(progressAnalysis(progress, { ...update, version: 2, sequence: 1 }), progress);
  assert.equal(progressAnalysis(progress, { ...update, state: "complete", stage: "complete", version: 4, sequence: 3 }), progress);
  const terminal = acceptAnalysis(progress, saved("complete", "complete", 4, 3), true);
  assert.equal(acceptAnalysis(terminal, saved(), true), terminal); assert.equal(progressAnalysis(terminal, { ...update, version: 5, sequence: 4 }), terminal);
  assert.equal(analysisRequests(terminal).length, 0);
});

test("late authorized terminal snapshots are masked after grant loss and cannot restore deleted chats", () => {
  const state = acceptAnalysis(initial(), saved(), true); state.records[CHAT].draft = "Keep my unsent draft";
  const masked = acceptAnalysis(state, saved("complete", "complete", 4, 3), false);
  assert.equal(JSON.stringify(masked).includes("PRIVATE_"), false); assert.equal(masked.records[CHAT].draft, "Keep my unsent draft");
  const deleted = removeConversation(state, CHAT); assert.equal(acceptAnalysis(deleted, saved("complete", "complete", 4, 3), true), deleted);
});

test("old cancelled/error completion preserves newer drafts, operations, titles and later messages", () => {
  const state = acceptAnalysis(initial(), saved(), true); state.records[CHAT].draft = "Newer draft"; state.records[CHAT].revision = 4; state.records[CHAT].title = "Newer title";
  let next = acceptAnalysis(state, saved("cancelled", "cancelled", 4, 3), true);
  assert.equal(next.records[CHAT].draft, "Newer draft"); assert.equal(next.records[CHAT].title, "Newer title");
  state.records[CHAT].draft = ""; state.records[CHAT].operation = { clientId: "newer-op" };
  next = acceptAnalysis(state, saved("error", "error", 4, 3), true); assert.equal(next.records[CHAT].draft, ""); assert.equal(next.records[CHAT].operation.clientId, "newer-op");
  state.records[CHAT].operation = null; state.records[CHAT].messages.push({ id: "later-reply", role: "aqua", sequence: 4 });
  assert.equal(acceptAnalysis(state, saved("cancelled", "cancelled", 4, 3), true).records[CHAT].draft, "");
});

test("observer discovery is unique, bounded to four and prioritizes the active chat", () => {
  const state = initial(); state.records = Object.fromEntries(Array.from({ length: 12 }, (_, index) => [`chat-${index}`, { id: `chat-${index}`, messages: [
    { role: "aqua", status: "pending", requestId: `request-${index}` }, { role: "aqua", status: "pending", requestId: `request-${index}` }] }])); state.activeId = "chat-11";
  const jobs = analysisRequests(state); assert.equal(jobs.length, 4); assert.equal(jobs[0].chatId, "chat-11"); assert.equal(new Set(jobs.map((job) => job.id)).size, 4);
});

test("truthful fixed stage copy separates cancellation requested from server confirmed", () => {
  assert.equal(analysisLabel({ stage: "cancelling" }), "Cancellation requested"); assert.equal(analysisLabel({ stage: "cancelled" }), "Analysis cancelled on the server");
  assert.match(analysisConnectionLabel("cancel-unconfirmed"), /could not be confirmed/); assert.equal(analysisLabel({ stage: "PRIVATE_REASONING" }).includes("PRIVATE"), false);
});

test("inactive terminal results retain bounded request metadata and drafts without growing transcript caches", () => {
  const state = acceptAnalysis(initial(), saved(), true); state.activeId = "another-chat"; state.records[CHAT].draft = "Keep this unsent text";
  const next = acceptAnalysis(state, saved("complete", "complete", 4, 3), true);
  assert.equal(next.records[CHAT].loaded, false); assert.deepEqual(next.records[CHAT].messages, []); assert.equal(next.records[CHAT].draft, "Keep this unsent text");
  assert.equal(next.records[CHAT].analyses[REQUEST].state, "complete"); assert.equal(JSON.stringify(next).includes("PRIVATE_RESULT"), false);
});
