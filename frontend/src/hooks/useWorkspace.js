import { useCallback, useEffect, useRef, useState } from "react";
import { listModels, listMessages, submitQuestion, updateChat, deleteChat, operationId } from "../services/aquaClient.js";
import { changeRecord, emptyConversation, failSubmission, finishHistory, finishSubmission, initialWorkspace, maskSavedResults, openConversation, removeConversation } from "./workspaceState.js";
import { useWorkspaceLists } from "./useWorkspaceLists.js";

export function useWorkspace({ canQuery, canReadResults = canQuery, csrfToken, onAuthFailure, suspended = false }) {
  const [state, setState] = useState(initialWorkspace), [models, setModels] = useState([]), [selectedModelId, setModelId] = useState("");
  const current = useRef(state), access = useRef(null), alive = useRef(true), requests = useRef(new Map()), reads = useRef(new Set()), messageEpoch = useRef(new Map()), historyReads = useRef(new Map());
  access.current = { canQuery, canReadResults, csrfToken, onAuthFailure, suspended }; current.current = state;
  const update = useCallback((transform) => { if (!alive.current) return; const next = transform(current.current); current.current = next; setState(next); }, []);
  const onError = useCallback((error) => { update((previous) => ({ ...previous, notice: error.message || "AQUA could not complete this action." }));
    if ([401, 403].includes(error.status)) access.current.onAuthFailure?.(); }, [update]);
  const library = useWorkspaceLists({ csrfToken, onError, enabled: !suspended });
  useEffect(() => { alive.current = true; return () => { alive.current = false; for (const entry of requests.current.values()) entry.abort();
    for (const entry of reads.current) entry.abort(); requests.current.clear(); }; }, []);
  useEffect(() => { const controller = new AbortController();
    listModels({ demoMode: false, signal: controller.signal }).then((items) => { if (!alive.current || controller.signal.aborted) return;
      setModels(items); setModelId((previous) => items.some((item) => item.id === previous) ? previous : items[0]?.id || ""); }).catch(() => {});
    return () => controller.abort(); }, []);
  useEffect(() => { if (canReadResults) return;
    for (const [id, controller] of historyReads.current) { messageEpoch.current.set(id, (messageEpoch.current.get(id) || 0) + 1); controller.abort(); }
    for (const controller of requests.current.values()) controller.abort();
    update((previous) => ({ ...previous, records: Object.fromEntries(Object.entries(previous.records).map(([id, item]) => [id,
      { ...item, historyLoading: false, messages: maskSavedResults(item.messages, false) }])) }));
  }, [canReadResults, update]);
  const active = state.records[state.activeId];
  const loadMessages = useCallback(async (id, older = false) => {
    if (id.startsWith("draft-")) return;
    historyReads.current.get(id)?.abort(); const controller = new AbortController(); reads.current.add(controller); historyReads.current.set(id, controller);
    const ticket = (messageEpoch.current.get(id) || 0) + 1; messageEpoch.current.set(id, ticket);
    const cursor = older ? current.current.records[id]?.olderCursor : null;
    update((previous) => changeRecord(previous, id, (item) => ({ ...item, historyLoading: true })));
    try { const page = await listMessages(id, { cursor, signal: controller.signal });
      if (controller.signal.aborted || !alive.current || messageEpoch.current.get(id) !== ticket) return;
      update((previous) => finishHistory(previous, id, page, older, access.current.canReadResults));
    } catch (error) { if (error.name !== "AbortError" && messageEpoch.current.get(id) === ticket) { update((previous) => changeRecord(previous, id, (item) => ({ ...item, historyLoading: false,
      ...([403, 404].includes(error.status) ? { messages: [], loaded: true } : {}) }))); onError(error); } }
    finally { reads.current.delete(controller); if (historyReads.current.get(id) === controller) historyReads.current.delete(id); }
  }, [update, onError]);
  const selectConversation = (id) => { const summary = library.chats.items.find((item) => item.id === id) || current.current.records[id]; if (!summary) return;
    update((previous) => openConversation(previous, summary)); void loadMessages(id); };
  const startConversation = () => { const previous = current.current;
    const empty = Object.values(previous.records).find((item) => item.id.startsWith("draft-") && !item.messages.length && !item.draft);
    if (empty) { update((value) => ({ ...value, activeId: empty.id, notice: "" })); return empty.id; }
    if (Object.keys(previous.records).length >= 100) { onError(new Error("Keep up to 100 unsent drafts in this visit. Reuse an existing chat.")); return null; }
    const item = emptyConversation(); update((value) => ({ ...value, records: { ...value.records, [item.id]: item }, activeId: item.id, notice: "" })); return item.id; };
  const run = useCallback(async (recordId, operation) => {
    if (!access.current.canQuery || access.current.suspended || requests.current.has(recordId)) return;
    if (requests.current.size >= 4) { onError(new Error("Wait for another open request to finish before asking another question.")); return; }
    const controller = new AbortController(); requests.current.set(recordId, controller);
    messageEpoch.current.set(recordId, (messageEpoch.current.get(recordId) || 0) + 1);
    update((previous) => changeRecord(previous, recordId, (item) => ({ ...item, operation: { ...operation, busy: true, uncertain: false } })));
    try { const result = await submitQuestion(operation.submission, { csrfToken: access.current.csrfToken, signal: controller.signal });
      if (controller.signal.aborted || !alive.current) return;
      messageEpoch.current.set(result.chat.id, (messageEpoch.current.get(result.chat.id) || 0) + 1);
      update((previous) => finishSubmission(previous, recordId, operation.clientId, result, access.current.canReadResults)); void library.refreshChats();
    } catch (error) { if (!alive.current) return;
      const uncertain = !error.status || error.status >= 500;
      update((previous) => failSubmission(previous, recordId, operation, uncertain));
      if (error.name !== "AbortError") onError(error);
    } finally { if (requests.current.get(recordId) === controller) requests.current.delete(recordId); }
  }, [update, library.refreshChats, onError]);
  const submit = (raw) => { const item = current.current.records[current.current.activeId], prompt = raw.trim();
    if (!prompt || prompt.length > 2000 || item.operation || !access.current.canQuery || !selectedModelId) return null;
    if (requests.current.size >= 4) { onError(new Error("Wait for another open request to finish before asking another question.")); return null; }
    const clientId = operationId(), userId = `local-${clientId}`, operation = { clientId, prompt,
      submission: { client_request_id: clientId, question: prompt, model: selectedModelId, ...(item.id.startsWith("draft-")
        ? library.filters.projectId ? { project_id: library.filters.projectId } : {} : { chatId: item.id }) } };
    update((previous) => changeRecord(previous, item.id, (record) => ({ ...record, draft: "", title: record.messageCount ? record.title : prompt.replace(/\s+/g, " ").slice(0, 120),
      messages: [...record.messages, { id: userId, role: "user", content: prompt, optimisticOperation: clientId }], operation })));
    void run(item.id, operation); return userId; };
  const retry = (messageId) => { const item = current.current.records[current.current.activeId];
    if (item.operation) { if (!item.operation.busy) void run(item.id, item.operation); return; }
    const reply = item.messages.find((message) => message.id === messageId), input = item.messages.find((message) => message.id === reply?.replyTo);
    if (!input || !reply?.response?.error?.retryable) return;
    const clientId = operationId(); void run(item.id, { clientId, prompt: input.content,
      submission: { chatId: item.id, retryInputId: input.id, client_request_id: clientId } }); };
  const mutateChat = async (item, values, remove = false) => {
    if (!item?.revision || requests.current.has(item.id)) return false;
    const controller = new AbortController(); reads.current.add(controller);
    try { const options = { csrfToken: access.current.csrfToken, signal: controller.signal };
      const saved = remove ? await deleteChat(item.id, item.revision, options) : await updateChat(item.id, { revision: item.revision, ...values }, options);
      if (!alive.current || controller.signal.aborted) return false;
      if (remove) update((previous) => removeConversation(previous, item.id));
      else update((previous) => changeRecord(previous, item.id, (record) => ({ ...record, ...saved })));
      await library.refreshChats(); return true;
    } catch (error) { if (error.name !== "AbortError") onError(error); return false; } finally { reads.current.delete(controller); }
  };
  const conversations = library.chats.items.map((summary) => ({ ...current.current.records[summary.id], ...summary }));
  return { durable: true, ...library, conversations, activeConversationId: state.activeId, active, messages: maskSavedResults(active.messages, canReadResults), draft: active.draft,
    pending: Boolean(active.operation?.busy), waiting: Boolean(active.operation?.busy), uncertain: Boolean(active.operation?.uncertain), notice: state.notice,
    models, selectedModelId, setModelId, faqs: library.starters, submit, retry, startConversation, selectConversation,
    drafts: Object.values(state.records).filter((item) => item.draft.trim()),
    stop: () => requests.current.get(current.current.activeId)?.abort(),
    setDraft: (draft) => update((previous) => changeRecord(previous, previous.activeId, (item) => ({ ...item, draft: String(draft).slice(0, 2000) }))),
    refresh: () => { void loadMessages(current.current.activeId); void library.refreshChats(); },
    loadOlder: () => loadMessages(state.activeId, true), mutateChat,
    checkSaved: () => { const item = current.current.records[current.current.activeId]; if (item.operation && !item.operation.busy) void run(item.id, item.operation); }
  };
}
