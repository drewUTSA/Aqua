import assert from "node:assert/strict";
import test from "node:test";
import { recentChats, recoverableChats } from "../src/components/workspace/sidebarState.js";

test("contextual recovery preserves unsent text and uncertain or running requests without submitting", () => {
  const draft = { id: "draft", title: "Unsent", draft: "Private unsent text" };
  const uncertain = { id: "uncertain", title: "Pending", draft: "", operation: { uncertain: true } };
  const active = { id: "active", title: "Running", draft: "", operation: { busy: true } };
  const chat = { recoverableDrafts: [draft, uncertain, draft], active, pending: true }, snapshot = structuredClone(chat);
  assert.deepEqual(recoverableChats(chat).map((item) => item.id), ["draft", "uncertain", "active"]);
  assert.equal(recoverableChats(chat)[0].draft, "Private unsent text"); assert.deepEqual(chat, snapshot);
});
test("recovery and recents retain account-local numeric bounds", () => {
  const items = Array.from({ length: 120 }, (_, index) => ({ id: `draft-${index}`, draft: "text" }));
  assert.equal(recoverableChats({ recoverableDrafts: items }).length, 100);
  assert.equal(recentChats({ durable: true, conversations: items.map((item) => ({ ...item, messageCount: 1 })) }).length, 100);
});
test("unsubmitted empty records stay out of recents while every submitted chat remains navigable", () => {
  const rows = [{ id: "empty", messageCount: 0 }, { id: "saved", messageCount: 2 }];
  assert.deepEqual(recentChats({ durable: true, conversations: rows }).map((item) => item.id), ["saved"]);
  assert.deepEqual(recentChats({ conversations: [{ id: "empty", messages: [] }, { id: "visit", messages: [{ role: "user" }] }] }).map((item) => item.id), ["visit"]);
});
