import { useEffect, useRef, useState } from "react";
import { listChats } from "../../services/workspaceClient.js";

const empty = { projectId: null, items: [], cursor: null, fromCursor: false, loading: false, error: "" };
// One expanded project page at a time: twenty server-capped summaries, explicit
// navigation only, and an abort/generation fence across account unmounts.
export function useProjectChats(auth) {
  const [state, setState] = useState(empty), current = useRef(state), pending = useRef(null), generation = useRef(0), alive = useRef(true);
  const authRef = useRef(auth); authRef.current = auth;
  const update = (value) => { if (alive.current) { current.current = value; setState(value); } };
  const close = () => { generation.current++; pending.current?.abort(); update(empty); };
  useEffect(() => { alive.current = true; return () => { alive.current = false; generation.current++; pending.current?.abort(); }; }, []);
  const load = async (projectId, cursor = null) => {
    const ticket = ++generation.current; pending.current?.abort(); const controller = new AbortController(); pending.current = controller;
    update({ ...empty, ...(current.current.projectId === projectId ? current.current : {}), projectId, loading: true, error: "" });
    try {
      const page = await listChats({ projectId, cursor, signal: controller.signal });
      if (!alive.current || ticket !== generation.current || controller.signal.aborted) return;
      if (page.items.length > 20 || page.items.some((item) => item.projectId !== projectId || item.archived)) throw new Error("project_page_invalid");
      update({ projectId, items: page.items, cursor: page.cursor, fromCursor: Boolean(cursor), loading: false, error: "" });
    } catch (error) {
      if (!alive.current || ticket !== generation.current || controller.signal.aborted) return;
      update({ ...current.current, loading: false, error: "Project chats could not be loaded. Retry when your connection is ready." });
      if ([401, 403].includes(error.status)) void authRef.current.refresh?.();
    }
  };
  return { ...state, close, load, toggle: (id) => current.current.projectId === id ? close() : void load(id),
    refresh: () => { if (current.current.projectId) void load(current.current.projectId); } };
}
