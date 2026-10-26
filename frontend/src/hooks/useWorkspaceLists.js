import { useCallback, useEffect, useRef, useState } from "react";
import { listChats, listProjects, listPrompts, listStarters, saveProject, deleteProject, savePrompt, deletePrompt, usePrompt, operationId } from "../services/aquaClient.js";

export function useWorkspaceLists({ csrfToken, onError, enabled = true }) {
  const [chats, setChats] = useState({ items: [], cursor: null, loading: true }), [projects, setProjects] = useState({ items: [], cursor: null, loading: true }),
    [prompts, setPrompts] = useState({ items: [], cursor: null, loading: true }), [starters, setStarters] = useState([]),
    [filters, setFilters] = useState({ search: "", archived: false, projectId: null }), [busy, setBusy] = useState(false);
  const current = useRef(null), generation = useRef(0), alive = useRef(true), pending = useRef(new Set()), mutationLock = useRef(false), namedReads = useRef(new Map());
  current.current = { csrfToken, onError, filters };
  const options = () => ({ csrfToken: current.current.csrfToken });
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; for (const controller of pending.current) controller.abort(); }; }, []);
  const read = useCallback(async (callback, kind) => {
    if (kind) namedReads.current.get(kind)?.abort();
    const controller = new AbortController(); pending.current.add(controller);
    if (kind) namedReads.current.set(kind, controller);
    try { const result = await callback(controller.signal); if (controller.signal.aborted) throw new DOMException("Request cancelled", "AbortError"); return result;
    } finally { pending.current.delete(controller);
      if (namedReads.current.get(kind) === controller) namedReads.current.delete(kind); }
  }, []);
  const refreshChats = useCallback(async (cursor = null, selected = current.current.filters) => {
    const ticket = ++generation.current;
    setChats((previous) => ({ ...previous, loading: true }));
    try { const page = await read((signal) => listChats({ ...selected, cursor, signal, ...options() }), "chats");
      if (alive.current && ticket === generation.current) setChats({ ...page, loading: false });
    } catch (error) { if (alive.current && ticket === generation.current && error.name !== "AbortError") { setChats((previous) => ({ ...previous, loading: false })); current.current.onError(error); } }
  }, [read]);
  const refreshPersonal = useCallback(async (kind, cursor = null) => {
    const load = kind === "projects" ? listProjects : listPrompts, save = kind === "projects" ? setProjects : setPrompts;
    save((previous) => ({ ...previous, loading: true }));
    try { const page = await read((signal) => load({ cursor, signal }), kind); if (alive.current) save({ ...page, fromCursor: cursor, loading: false }); }
    catch (error) { if (alive.current && error.name !== "AbortError") { save((previous) => ({ ...previous, loading: false })); current.current.onError(error); } }
  }, [read]);
  useEffect(() => { if (!enabled) return; void refreshChats(null, filters); }, [enabled, filters, refreshChats]);
  useEffect(() => { if (!enabled) return; void refreshPersonal("projects"); void refreshPersonal("prompts");
    void read((signal) => listStarters({ signal })).then((items) => { if (alive.current) setStarters(items); }).catch((error) => {
      if (alive.current && error.name !== "AbortError") current.current.onError(error);
    });
  }, [enabled, read, refreshPersonal]);
  const mutate = async (action, kind) => {
    if (mutationLock.current) return false; mutationLock.current = true; setBusy(true);
    try { await read((signal) => action({ ...options(), signal })); if (!alive.current) return false;
      await refreshPersonal(kind); if (kind === "projects") await refreshChats(); return true;
    } catch (error) { if (alive.current && error.name !== "AbortError") current.current.onError(error); return false; }
    finally { mutationLock.current = false; if (alive.current) setBusy(false); }
  };
  return { chats, projects, prompts, starters, filters, busy, refreshChats,
    filter: (value) => setFilters((previous) => ({ ...previous, ...value })),
    moreChats: () => refreshChats(chats.cursor), moreProjects: () => refreshPersonal("projects", projects.cursor), morePrompts: () => refreshPersonal("prompts", prompts.cursor),
    firstProjects: () => refreshPersonal("projects"), firstPrompts: () => refreshPersonal("prompts"),
    saveProject: (item, name, requestId) => mutate((opts) => saveProject(item?.id, item ? { revision: item.revision, name } : { client_request_id: requestId || operationId(), name }, opts), "projects"),
    deleteProject: (item) => { if (current.current.filters.projectId === item.id) setFilters((previous) => ({ ...previous, projectId: null }));
      return mutate((opts) => deleteProject(item.id, item.revision, opts), "projects"); },
    savePrompt: (item, values, requestId) => mutate((opts) => savePrompt(item?.id, item ? { revision: item.revision, ...values } : { client_request_id: requestId || operationId(), ...values }, opts), "prompts"),
    deletePrompt: (item) => mutate((opts) => deletePrompt(item.id, item.revision, opts), "prompts"),
    usePrompt: async (item) => { const okay = await mutate((opts) => usePrompt(item.id, { client_request_id: operationId() }, opts), "prompts"); return okay; }
  };
}
