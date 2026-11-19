import assert from "node:assert/strict";
import test from "node:test";
import { canStartGroupRank, initialRankFields, rankGroupsDraft, rankLabel } from "../src/components/workspace/rankGroupsDraft.js";
import { applyEmptyChatDraft, initialWorkspace } from "../src/hooks/workspaceState.js";

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
