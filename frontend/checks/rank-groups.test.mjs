import assert from "node:assert/strict";
import test from "node:test";
import { canStartGroupRank, initialRankFields, rankGroupsDraft, rankLabel } from "../src/components/workspace/rankGroupsDraft.js";
import { applyEmptyChatDraft, initialWorkspace, isEmptyChatDraft, matchesRankRecovery, rankTimeoutReply } from "../src/hooks/workspaceState.js";

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
test("the option only appears in an empty, visible, authorized new durable chat", () => {
  const auth = { canQuery: true, session: { can_query: true } };
  const chat = { durable: true, activeConversationId: "draft-test", draft: "", active: {} };
  const allowed = (a = auth, c = chat, view = {}) => canStartGroupRank({ visible: true, active: false, ...view, chat: c, auth: a });
  assert.equal(allowed(), true);
  for (const patch of [{ durable: false }, { pending: true }, { uncertain: true }, { draft: " " }, { activeConversationId: "saved" },
    { active: { archived: true } }, { active: { historyLoading: true } }]) assert.equal(allowed(auth, { ...chat, ...patch }), false);
  for (const patch of [{ canQuery: false }, { session: {} }, { demoMode: true }]) assert.equal(allowed({ ...auth, ...patch }), false);
  assert.equal(allowed(auth, chat, { active: true }), false);
  assert.equal(allowed(auth, chat, { visible: false }), false);
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
  assert.equal(rankTimeoutReply(failed), timeout);
  assert.equal(rankTimeoutReply({ ...failed, draft: "" }), timeout);
  const again = { ...timeout, sequence: 3, id: "retry-reply", requestId: "second-request" };
  assert.equal(rankTimeoutReply({ ...failed, messages: [user, timeout, again], messageCount: 3 }), again);
});

test("recovery needs the latest terminal reply, its own original input, and an unedited source draft", () => {
  for (const patch of [{ loaded: false }, { archived: true }, { historyLoading: true }, { operation: {} },
    { revision: null }, { draft: "An unsent edit" }, { messageCount: 3 }, { messages: [timeout] },
    { messages: [user, { ...timeout, role: "user" }] }, { messages: [user, { ...timeout, status: "pending" }] },
    { messages: [user, { ...timeout, resultUnavailable: true }] }, { messages: [user, { ...timeout, replyTo: "another input" }] },
    { messages: [{ ...user, conversationId: "other-chat" }, timeout] },
    { messages: [user, { ...timeout, conversationId: "other-chat" }] },
    { messages: [user, { ...timeout, response: { status: "error", error: { code: "model_unavailable" } } }] }]) {
    assert.equal(rankTimeoutReply({ ...failed, ...patch }), null);
  }
});

test("the recovery offer is limited to ordinary ranking language in the linked input", () => {
  const check = content => rankTimeoutReply({ ...failed, draft: "", messages: [{ ...user, content }, timeout] });
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
  const binding = { ownerId: history.owner, chatId: savedChat, replyId: timeout.id, requestId: timeout.requestId };
  assert.ok(matchesRankRecovery(state, access, history, binding));
  for (const patch of [{ ownerId: "" }, { ownerId: "other employee" }, { chatId: "another chat" }, { requestId: "other request" }, { replyId: "other reply" }]) {
    assert.equal(matchesRankRecovery(state, access, history, { ...binding, ...patch }), false);
  }
  for (const patch of [{ canReadResults: false }, { canQuery: false }, { suspended: true }]) {
    assert.equal(matchesRankRecovery(state, { ...access, ...patch }, history, binding), false);
  }
  assert.equal(matchesRankRecovery({ ...state, activeId: "new view" }, access, history, binding), false);
  assert.equal(matchesRankRecovery({ ...state, deletedChatIds: [savedChat] }, access, history, binding), false);
  assert.equal(matchesRankRecovery({ ...state, records: { [savedChat]: { ...failed, draft: "new notes" } } }, access, history, binding), false);
});

test("the reused destination must also be empty enough to apply the eventual manual draft", () => {
  const initial = initialWorkspace(), destination = initial.records[initial.activeId];
  assert.ok(isEmptyChatDraft(destination));
  for (const patch of [{ id: savedChat }, { draft: " " }, { messageCount: 1 }, { messages: [user] },
    { operation: {} }, { historyLoading: true }, { archived: true }]) assert.equal(isEmptyChatDraft({ ...destination, ...patch }), false);
});
