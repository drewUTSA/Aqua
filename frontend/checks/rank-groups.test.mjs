import assert from "node:assert/strict";
import test from "node:test";
import { canStartGroupRank, initialRankFields, rankGroupsDraft, rankLabel } from "../src/components/workspace/rankGroupsDraft.js";
import { applyEmptyChatDraft, applyRankingPreview, initialWorkspace, isEmptyChatDraft, matchesSavedRank, savedRankReply } from "../src/hooks/workspaceState.js";

const fields = { ...initialRankFields, source: "observations", group: "stations", field: "rainfall", number: "2" };
for (const direction of ["top", "bottom"]) {
  for (const [measure, phrase] of [["count", "row count"], ["total", "total rainfall"]]) {
    const common = { ...fields, direction, measure };
    test(`${direction} by ${measure} distinguishes fixed groups, cutoff peers and distinct scores`, () => {
      const stem = "Rank groups: From observations, ";
      assert.equal(rankGroupsDraft({ ...common, ties: "fixed" }), stem + `show exactly the ${direction} 2 stations by ${phrase}.`);
      assert.equal(rankGroupsDraft({ ...common, ties: "peers" }), stem + `show the ${direction} 2 stations by ${phrase}, including ties.`);
      assert.equal(rankGroupsDraft({ ...common, ties: "levels" }), stem + `which stations have one of the ${direction === "top" ? "highest" : "lowest"} 2 distinct ${phrase} values?`);
    });
  }
}
test("only bounded names, whole levels and supported options create an explicit draft", () => {
  for (const value of ["North-East", "office_id", "shift 2"]) assert.equal(rankLabel(value), value);
  for (const value of [null, "", "a".repeat(65), "first, second", "one.two", "logs\nby day", "<tag>", "9A"]) {
    assert.equal(rankLabel(value), "");
    assert.equal(rankGroupsDraft({ ...fields, group: value }), "");
  }
  for (const number of ["", "0", "1001", "2.5", "1e2", "-2", "03"]) assert.equal(rankGroupsDraft({ ...fields, number }), "");
  for (const number of ["1", "1000"]) assert.ok(rankGroupsDraft({ ...fields, number }));
  for (const invalid of [{ ties: "unknown" }, { direction: "up" }, { measure: "max" }, { measure: "total", field: "" }]) {
    assert.equal(rankGroupsDraft({ ...fields, ...invalid }), "");
  }
});
test("a new authorized chat offers ranking on a blank draft or while typing an ordinary ranking", () => {
  const auth = { canQuery: true, session: { can_query: true } };
  const chat = { durable: true, activeConversationId: "draft-test", draft: "", active: {} };
  const allowed = (a = auth, c = chat, view = {}) => canStartGroupRank({ visible: true, active: false, ...view, chat: c, auth: a });
  assert.equal(allowed(), true);
  assert.equal(allowed(auth, { ...chat, draft: "Which locations had the highest turnover?" }), true);
  for (const patch of [{ durable: false }, { pending: true }, { uncertain: true }, { draft: " " }, { activeConversationId: "saved" },
    { draft: "Count deposits of at least 100." }, { draft: "  Rank groups: From readings, show the top group." },
    { active: { archived: true } }, { active: { operation: {} } }, { active: { revision: 1 } },
    { active: { historyLoading: true } }]) assert.equal(allowed(auth, { ...chat, ...patch }), false);
  for (const patch of [{ canQuery: false }, { session: {} }, { demoMode: true }]) assert.equal(allowed({ ...auth, ...patch }), false);
  assert.equal(allowed(auth, chat, { active: true }), false);
  assert.equal(allowed(auth, chat, { visible: false }), false);
});

function composingRanking() {
  const state = initialWorkspace(), chatId = state.activeId, original = "  Which stations had the most readings? ";
  const projectId = "88ea088a-60b8-43a0-9fc6-a457e620e3e4";
  state.records[chatId] = { ...state.records[chatId], projectId, draft: original };
  const binding = { ownerId: "reader", chatId, original, projectId };
  const access = { canQuery: true, canReadResults: true, suspended: false };
  const history = { owner: binding.ownerId }, value = rankGroupsDraft(fields);
  const apply = (s = state, b = binding, a = access, h = history, v = value) => applyRankingPreview(s, a, h, b, v);
  return { state, binding, access, history, value, apply };
}
test("taking a preview keeps the exact original visit-local draft and opens an unsent ranking in the same project", () => {
  const { state, binding, value, apply } = composingRanking();
  const next = apply();
  assert.notEqual(next.activeId, binding.chatId);
  assert.equal(next.records[binding.chatId], state.records[binding.chatId]);
  assert.equal(next.records[binding.chatId].draft, binding.original);
  assert.deepEqual([next.records[next.activeId].draft, next.records[next.activeId].projectId], [value, binding.projectId]);
  for (const item of Object.values(next.records)) {
    assert.deepEqual(item.messages, []);
    assert.equal(item.messageCount, 0);
    assert.equal(item.operation, null);
    assert.equal(item.revision, null);
  }
});
test("a preview reuses only a blank visit-local draft in the original project, and respects capacity", () => {
  const { state, binding, value, apply } = composingRanking();
  const source = state.records[binding.chatId];
  for (let i = 1; i < 100; i++) {
    const id = `draft-${i}`;
    state.records[id] = { ...source, id, draft: "", projectId: null };
  }
  assert.equal(apply(), null);
  assert.equal(state.records[binding.chatId].draft, binding.original);
  const id = "draft-99";
  state.records[id].projectId = binding.projectId;
  const next = apply();
  assert.equal(next.activeId, id);
  assert.equal(next.records[id].draft, value);
  assert.equal(next.records["draft-1"], state.records["draft-1"]);
  assert.equal(Object.keys(next.records).length, 100);
});
test("a stale preview cannot open a new draft or change its source", () => {
  const { state, binding, access, history, value, apply } = composingRanking();
  for (const patch of [{ ownerId: "" }, { ownerId: "someone else" }, { chatId: "draft-another" }, { projectId: null }, { original: "old words" }]) {
    assert.equal(apply(state, { ...binding, ...patch }), state);
  }
  for (const patch of [{ canQuery: false }, { canReadResults: false }, { suspended: true }]) {
    assert.equal(apply(state, binding, { ...access, ...patch }), state);
  }
  assert.equal(apply(state, binding, access, { owner: "new owner" }), state);
  for (const patch of [{ operation: {} }, { revision: 1 }, { archived: true }, { historyLoading: true }, { messages: [{}] }, { messageCount: 1 }]) {
    const changed = { ...state, records: { [binding.chatId]: { ...state.records[binding.chatId], ...patch } } };
    assert.equal(apply(changed), changed);
  }
  for (const patch of [{ deletedChatIds: [binding.chatId] }, { activeId: "draft-another" }]) {
    const changed = { ...state, ...patch };
    assert.equal(apply(changed), changed);
  }
  assert.equal(apply(state,binding,access,history,""),state);
  assert.equal(apply(state,binding,access,history,value.padEnd(2001)),state);
});
test("empty first drafts receive the preview in place and unrelated wording stays in the composer", () => {
  const { state, binding, value, apply } = composingRanking();
  for (const original of ["Count all deposits.", "   ", "Rank groups: show top three."]) {
    state.records[binding.chatId].draft = original;
    assert.equal(apply(state, { ...binding, original }), state);
  }
  state.records[binding.chatId].draft = "";
  const next = apply(state, { ...binding, original: "" });
  assert.equal(next.activeId, binding.chatId);
  assert.equal(next.records[next.activeId].draft, value);
  assert.equal(Object.keys(next.records).length, 1);
});
test("a late form application cannot replace an existing draft or apply to a different chat", () => {
  const state = initialWorkspace(), id = state.activeId, value = rankGroupsDraft(fields);
  const first = applyEmptyChatDraft(state, id, value);
  assert.equal(first.records[id].draft, value);
  assert.equal(applyEmptyChatDraft(first, id, "replacement"), first);
  for (const patch of [{ draft: " " }, { archived: true }, { historyLoading: true }, { operation: {} }, { messages: [{}] }, { messageCount: 1 }]) {
    const changed = { ...state, records: { [id]: { ...state.records[id], ...patch } } };
    assert.equal(applyEmptyChatDraft(changed, id, value), changed);
  }
  const changed = { ...state, activeId: "draft-other" };
  assert.equal(applyEmptyChatDraft(changed, id, value), changed);
});

const savedChat = "48c67d63-4aa0-405e-a1ec-3dc48b79c775";
const question = "Which areas had the fewest registrations?";
const user = { id: "input", conversationId: savedChat, role: "user", status: "complete", sequence: 1, content: question };
const timeout = { id: "reply", requestId: "request", replyTo: user.id, conversationId: savedChat, role: "aqua",
  status: "error", sequence: 2, response: { status: "error", error: { code: "model_timeout", retryable: true } } };
const failed = { id: savedChat, loaded: true, revision: 2, messageCount: 2, draft: question, messages: [user, timeout] };

test("an eligible saved timeout matches the original question even after reload or a retry", () => {
  assert.equal(savedRankReply(failed), timeout);
  assert.equal(savedRankReply({ ...failed, draft: "" }), timeout);
  const again = { ...timeout, sequence: 3, id: "retry-reply", requestId: "second-request" };
  assert.equal(savedRankReply({ ...failed, messages: [user, timeout, again], messageCount: 3 }), again);
});

test("recovery needs the latest terminal reply, its own original input, and an unedited source draft", () => {
  for (const patch of [{ loaded: false }, { archived: true }, { historyLoading: true }, { operation: {} },
    { revision: null }, { draft: "An unsent edit" }, { messageCount: 3 }, { messages: [timeout] },
    { messages: [user, { ...timeout, role: "user" }] }, { messages: [user, { ...timeout, status: "pending" }] },
    { messages: [user, { ...timeout, resultUnavailable: true }] }, { messages: [user, { ...timeout, replyTo: "another input" }] },
    { messages: [{ ...user, conversationId: "other-chat" }, timeout] },
    { messages: [user, { ...timeout, conversationId: "other-chat" }] },
    { messages: [user, { ...timeout, response: { status: "error", error: { code: "model_unavailable" } } }] }]) {
    assert.equal(savedRankReply({ ...failed, ...patch }), null);
  }
});

test("the recovery offer is limited to ordinary ranking language in the linked input", () => {
  const check = content => savedRankReply({ ...failed, draft: "", messages: [{ ...user, content }, timeout] });
  for (const text of ["Rank departments by receipts.", "Show top three offices.", "Include groups tied for first."]) {
    assert.equal(check(text), timeout);
  }
  for (const text of ["", "Count transfers of at least $10.", "List transfers of at most $90.", "Explain payment processing.", "Rank groups: From loans, show the top groups."]) {
    assert.equal(check(text), null);
  }
});

test("a stale recovery action cannot navigate after identity, request, chat, grant or draft changes", () => {
  const state = { activeId: savedChat, records: { [savedChat]: failed } };
  const access = { canQuery: true, canReadResults: true, suspended: false };
  const history = { owner: "employee-a" };
  const binding = { ownerId: history.owner, chatId: savedChat, projectId: failed.projectId, replyId: timeout.id, requestId: timeout.requestId, status: timeout.status };
  assert.ok(matchesSavedRank(state, access, history, binding));
  for (const patch of [{ ownerId: "" }, { ownerId: "other employee" }, { chatId: "another chat" }, { requestId: "other request" }, { replyId: "other reply" }]) {
    assert.equal(matchesSavedRank(state, access, history, { ...binding, ...patch }), false);
  }
  for (const patch of [{ canReadResults: false }, { canQuery: false }, { suspended: true }]) {
    assert.equal(matchesSavedRank(state, { ...access, ...patch }, history, binding), false);
  }
  assert.equal(matchesSavedRank({ ...state, activeId: "new view" }, access, history, binding), false);
  assert.equal(matchesSavedRank({ ...state, deletedChatIds: [savedChat] }, access, history, binding), false);
  assert.equal(matchesSavedRank({ ...state, records: { [savedChat]: { ...failed, draft: "new notes" } } }, access, history, binding), false);
});

test("the reused destination must also be empty enough to apply the eventual manual draft", () => {
  const initial = initialWorkspace(), destination = initial.records[initial.activeId];
  assert.ok(isEmptyChatDraft(destination));
  for (const patch of [{ id: savedChat }, { draft: " " }, { messageCount: 1 }, { messages: [user] },
    { operation: {} }, { historyLoading: true }, { archived: true }]) assert.equal(isEmptyChatDraft({ ...destination, ...patch }), false);
});

const frostRequest = "0a2cb1c7-a444-418f-ad94-0e07f22d3800";
const frostReply = "8d3aeeda-cf83-40c0-ae0f-d37a3225aab6";
const frostInput = { ...user, content: "Which inspection zones tied for the most frost warnings?" };
const frostTable = { id: "result", columns: ["zone", "warnings"], rows: [["South", 9], ["Hill", 9]] };
const completed = { ...timeout, id: frostReply, requestId: frostRequest, status: "complete", historical: true, resultUnavailable: false,
  response: { status: "success", tables: [frostTable] } };
const saved = { ...failed, draft: "", projectId: "inspection-project", messages: [frostInput, completed] };

test("choosing tie rules is available on either a full or a partial saved ordinary ranking", () => {
  for (const rows of [frostTable.rows, frostTable.rows.slice(0, 1), []]) {
    const answer = { ...completed, response: { status: "success", tables: [{ ...frostTable, rows }] } };
    assert.equal(savedRankReply({ ...saved, messages: [frostInput, answer] }), answer);
  }
});

test("saved ranking choices require the latest visible table, its linked ordinary question, and an empty composer", () => {
  const changeReply = patch => ({ ...saved, messages: [frostInput, { ...completed, ...patch }] });
  for (const record of [
    { ...saved, messages: [{ ...frostInput, content: "Count the stations." }, completed] },
    { ...saved, messages: [{ ...frostInput, content: "Rank groups: From warnings, show the top 3 zones by row count, including ties." }, completed] },
    { ...saved, messages: [frostInput, completed, { ...frostInput, sequence: 3 }], messageCount: 3 },
    { ...saved, draft: frostInput.content }, { ...saved, analyses: { [frostRequest]: { state: "cancelled" } } },
    { ...saved, historyLoading: true }, { ...saved, archived: true },
    changeReply({ historical: false }), changeReply({ resultUnavailable: true }), changeReply({ replyTo: "missing" }),
    changeReply({ response: { status: "success", tables: [] } }), changeReply({ status: "error", response: { status: "error", error: { code: "model_unavailable" } } }),
  ]) assert.equal(savedRankReply(record), null);
});

test("a saved-answer action cannot cross the owner, project, access or outcome originally displayed", () => {
  const state = { activeId: savedChat, records: { [savedChat]: saved } };
  const access = { canQuery: true, canReadResults: true, suspended: false }, history = { owner: "employee" };
  const binding = { ownerId: history.owner, chatId: savedChat, projectId: saved.projectId, replyId: frostReply, requestId: frostRequest, status: "complete" };
  assert.equal(matchesSavedRank(state, access, history, binding), true);
  for (const patch of [{ ownerId: "different" }, { projectId: null }, { status: "error" }, { replyId: "older reply" }, { requestId: "different request" }]) {
    assert.equal(matchesSavedRank(state, access, history, { ...binding, ...patch }), false);
  }
  for (const patch of [{ canReadResults: false }, { canQuery: false }, { suspended: true }]) {
    assert.equal(matchesSavedRank(state, { ...access, ...patch }, history, binding), false);
  }
});
