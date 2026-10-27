import assert from "node:assert/strict";
import test from "node:test";
import { emptyVisualView, finishVisualView, matchingVisualReply, visualIntent, visualResult, visualToken } from "../src/services/visualResults.js";
import { plotlyFixture } from "./plotly-fixture.mjs";

const input = { id: "input", role: "user", sequence: 3, content: "Chart revenue" };
function reply(intent = "explicit", id = "reply", requestId = "request") {
  const { table, descriptor } = plotlyFixture();
  return { id, requestId, replyTo: input.id, sequence: 4, role: "aqua", response: { status: "success", tables: [table],
    presentation: { version: 1, intent, default_view: "chart", reason: "requested_visual", charts: [descriptor] } } };
}
function pending(view = emptyVisualView()) { return { ...view, pending: { userId: input.id, question: input.content, floor: 2, seen: [], intent: "explicit", dismissed: false } }; }

test("visual hints distinguish explanations/negation from chart requests and narrow followups", () => {
  for (const question of ["Explain the chart", "No chart please", "Do not show a chart", "What is a graph?",
    "Can you explain the chart?", "Please explain this chart", "Could you please describe the graph?", "Please can you tell me about this plot?",
    "Do not show me a chart", "Please don't show us any graphs", "I do not want to show a chart", "Could you not show me the plot?"]) assert.equal(visualIntent(question, true), "text");
  for (const question of ["Can you show a chart?", "Please could you plot revenue by month?", "No refunds were paid; show a chart"]) assert.equal(visualIntent(question, true), "explicit");
  assert.equal(visualIntent("Chart revenue"), "explicit"); assert.equal(visualIntent("Now only last year", true), "followup");
  assert.equal(visualIntent("Could you now only show last year?", true), "followup");
  assert.equal(visualIntent("Now only last year", false), "text"); assert.equal(visualIntent("Hello", true), "text");
});
test("polite explanations and negated visual followups keep a dismissed pane closed", () => {
  for (const question of ["Can you explain the chart?", "Please explain this chart", "Do not show me a chart"]) {
    const message = reply("text"), view = pending({ ...emptyVisualView(), selected: "old", open: false });
    view.pending.intent = visualIntent(question, true);
    const next = finishVisualView(view, message, visualResult(message, [input, message]));
    assert.equal(view.pending.intent, "text"); assert.equal(next.open, false); assert.equal(next.selected, "old");
  }
});
test("new chat has no visual selection or automatic mobile tab switch", () => {
  const view = emptyVisualView(); assert.equal(view.open, false); assert.equal(view.selected, null);
  const message = reply(), next = finishVisualView(pending(view), message, visualResult(message, [input, message]));
  assert.equal(next.open, true); assert.equal(next.selected, "reply"); assert.equal(next.tab, "conversation");
});
test("dismissal during a held explicit update wins over completion", () => {
  const message = reply(), view = pending(); view.pending.dismissed = true;
  const next = finishVisualView(view, message, visualResult(message, [input, message]));
  assert.equal(next.open, false); assert.equal(next.selected, message.id);
});
test("followup updates without reopening dismissed pane, text answers never steal selection", () => {
  const old = { ...emptyVisualView(), selected: "old", open: false }, followup = reply("followup");
  const next = finishVisualView(pending(old), followup, visualResult(followup, [input, followup]));
  assert.equal(next.open, false); assert.equal(next.selected, followup.id);
  const text = reply("text", "text"), after = finishVisualView(pending(next), text, visualResult(text, [input, text]));
  assert.equal(after.selected, followup.id); assert.equal(after.open, false);
});
test("failed refresh retains last valid selected result and records retry association", () => {
  const error = { id: "failed", response: { status: "error" } };
  const next = finishVisualView(pending({ ...emptyVisualView(), selected: "last-good", open: true }), error, null);
  assert.equal(next.selected, "last-good"); assert.equal(next.open, true); assert.equal(next.failed, "failed");
});
test("canonical request identity fences delayed older and cross-request replies", () => {
  const message = reply(), old = reply("explicit", "older", "stale"); old.replyTo = input.id;
  const view = pending(); view.pending.userId = "local-client";
  const analyses = { request: { id: "request", clientId: "client" } };
  assert.equal(matchingVisualReply(view.pending, [input, old, message], analyses), message);
  assert.equal(matchingVisualReply(view.pending, [old], analyses), null);
});
test("hydrated history is never selected without a pending or manual action", () => {
  const message = reply(); assert.equal(matchingVisualReply(null, [input, message]), null);
  assert.equal(finishVisualView(emptyVisualView(), message, visualResult(message, [input, message])).selected, null);
});
test("retry can replace same demo message or a new durable reply to the same input", () => {
  const previous = reply(), next = reply("explicit", "new-reply", "new-request"); next.sequence = 6;
  const marker = { ...pending().pending, floor: 4, retryId: previous.id, retryInput: input.id, seen: [visualToken(previous)] };
  assert.equal(matchingVisualReply(marker, [input, previous, next]), next);
  assert.equal(matchingVisualReply(marker, [previous]), null);
});
test("revoked or unavailable result has no derived chart/table payload", () => {
  const message = reply(); message.resultUnavailable = true;
  assert.equal(visualResult(message, [input, message]), null);
  assert.equal(visualResult({ ...message, resultUnavailable: false, response: { status: "error" } }, []), null);
});
test("legacy demo upgrade is bounded and retains row identity for table/exact provenance", () => {
  const { table } = plotlyFixture(); const message = { ...reply(), response: { status: "success", tables: [table],
    visualizations: [{ type: "bar", title: "Old chart", xKey: "label", yKey: "amount" }] } };
  const result = visualResult(message, [input, message]); assert.equal(result.descriptor.type, "bar"); assert.equal(result.table.rows, table.rows);
  message.response.precisionNote = "Exact values"; assert.equal(visualResult(message, [input, message]).descriptor, null);
});

test("malformed legacy chart metadata preserves the original table without throwing", () => {
  const { table } = plotlyFixture();
  for (const invalid of [{ title: {} }, { series: [{ key: "amount", label: {} }] }, { series: "amount" }, { xKey: {} }, { series: [{ key: "amount" }, { key: "other" }] }]) {
    const message = { ...reply(), response: { status: "success", tables: [table], visualizations: [null, { type: "bar", title: "Old chart", xKey: "label", yKey: "amount", ...invalid }] } };
    const result = visualResult(message, [input, message]); assert.equal(result.descriptor, null); assert.equal(result.table, table);
  }
  const malformed = { ...reply(), response: { status: "success", tables: [{ ...table, rows: null }], visualizations: [{ type: "bar", xKey: "label", yKey: "amount" }] } };
  assert.doesNotThrow(() => visualResult(malformed, [])); assert.equal(visualResult(malformed, []).descriptor, null);
});
