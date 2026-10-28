import { useEffect, useRef, useState } from "react";
import { emptyVisualView, finishVisualView, matchingVisualReply, visualIntent, visualResult, visualToken } from "../services/visualResults.js";

/** IDs and interaction state only. Authorized chat messages own every payload. */
export function useVisualResults(chat, allowed, initialView = "chart") {
  const key = chat.active?.viewId || chat.activeConversationId;
  const [views, setViews] = useState({});
  const current = useRef(views); current.current = views;
  const view = views[key] || emptyVisualView();
  const change = (transform) => setViews((previous) => {
    const next = { ...previous, [key]: transform(previous[key] || emptyVisualView()) };
    // The transport also bounds mounted chats; this view ledger holds no data.
    const ids = Object.keys(next); if (ids.length > 100) delete next[ids.find((id) => id !== key)];
    current.current = next; return next;
  });
  useEffect(() => { if (!allowed) { current.current = {}; setViews({}); } }, [allowed]);
  useEffect(() => {
    if (!allowed || !view.pending) return;
    const reply = matchingVisualReply(view.pending, chat.messages, chat.active?.analyses);
    if (!reply) return;
    const completed = visualResult(reply, chat.messages);
    const next = finishVisualView(view, reply, completed);
    if (next !== view) change(() => ({ ...next, mode: !view.selected && initialView === "table" && completed?.intent !== "explicit" ? "table" : next.mode }));
  }, [allowed, key, chat.messages, chat.active?.analyses, view]);

  const begin = (question, retryId = null) => {
    const previous = current.current[key] || emptyVisualView();
    const intent = visualIntent(question, Boolean(previous.selected));
    return { question, retryId, intent, userId: null, dismissed: false,
      floor: Math.max(0, ...chat.messages.map((item) => item.sequence || 0)), seen: chat.messages.filter((item) => item.role === "aqua").map(visualToken) };
  };
  const submit = (question) => {
    const pending = begin(question), userId = chat.submit(question);
    if (userId) change((previous) => ({ ...previous, pending: { ...pending, userId }, failed: null,
      open: pending.intent === "explicit" || previous.open }));
    return userId;
  };
  const retry = (id) => {
    const reply = chat.messages.find((item) => item.id === id);
    const question = chat.messages.find((item) => item.id === reply?.replyTo)?.content || chat.draft;
    const pending = { ...begin(question, id), retryInput: reply?.replyTo };
    chat.retry(id);
    change((previous) => ({ ...previous, pending, failed: null }));
  };
  const selected = allowed ? chat.messages.find((item) => item.id === view.selected) : null;
  const result = visualResult(selected, chat.messages);
  // Revocation, deletion and unavailable snapshots remove the payload during
  // this render, before an effect or a delayed chart import can run.
  const open = allowed && view.open && Boolean(result || view.pending?.intent === "explicit");
  return { view, open, result, selected, change, chat: { ...chat, submit, retry },
    show: (id) => { const item = chat.messages.find((message) => message.id === id);
      const value = visualResult(item, chat.messages); if (!allowed || !value) return;
      change((previous) => ({ ...previous, selected: id, open: true, expanded: false, mode: value.descriptor && (initialView !== "table" || value.intent === "explicit") ? "chart" : "table" })); },
    close: () => change((previous) => ({ ...previous, open: false, expanded: false, tab: "conversation",
      pending: previous.pending ? { ...previous.pending, dismissed: true } : null })) };
}
