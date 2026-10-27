import { useCallback, useEffect, useRef, useState } from "react";
import { cancelAnalysis } from "../services/aquaClient.js";
import { observeAnalysis } from "../services/analysisObserver.js";

export function useAnalysisRequests({ jobs, enabled, csrfToken, onSnapshot, onProgress, onError }) {
  const current = useRef(null), observers = useRef(new Map()), mutations = useRef(new Map()), mounted = useRef(true), pending = useRef(new Map()), frame = useRef(null);
  const [connections, setConnections] = useState({}), [revision, setRevision] = useState(0), [visible, setVisible] = useState(() => typeof document === "undefined" || document.visibilityState !== "hidden");
  current.current = { jobs, csrfToken, onSnapshot, onProgress, onError };
  const key = jobs.map((job) => job.id).sort().join(",");
  const mark = useCallback((id, value) => { if (mounted.current) setConnections((previous) => ({ ...previous, [id]: value })); }, []);
  const flush = useCallback(() => {
    frame.current = null; const events = [...pending.current.values()]; pending.current.clear();
    for (const { event, valid } of events) if (valid()) current.current.onProgress(event);
  }, []);
  useEffect(() => { mounted.current = true;
    const foreground = () => { setVisible(document.visibilityState !== "hidden"); };
    const online = () => setRevision((value) => value + 1);
    document.addEventListener("visibilitychange", foreground); window.addEventListener("online", online);
    return () => { mounted.current = false; document.removeEventListener("visibilitychange", foreground); window.removeEventListener("online", online);
      for (const controller of observers.current.values()) controller.abort(); for (const controller of mutations.current.values()) controller.abort(); };
  }, []);
  useEffect(() => {
    for (const controller of observers.current.values()) controller.abort(); observers.current.clear();
    pending.current.clear(); if (frame.current !== null) cancelAnimationFrame(frame.current); frame.current = null;
    const ids = new Set(current.current.jobs.slice(0, 4).map((job) => job.id));
    setConnections((previous) => Object.fromEntries(Object.entries(previous).filter(([id]) => ids.has(id))));
    if (!enabled || !visible) return;
    for (const { id } of current.current.jobs.slice(0, 4)) {
      const controller = new AbortController(); observers.current.set(id, controller);
      const valid = () => mounted.current && !controller.signal.aborted && observers.current.get(id) === controller;
      void observeAnalysis(id, { signal: controller.signal,
        onConnection: (value) => { if (valid()) mark(id, value); },
        onSnapshot: (snapshot) => { pending.current.delete(id); if (valid()) current.current.onSnapshot(snapshot); },
        onProgress: (event) => { if (!valid()) return; pending.current.set(id, { event, valid });
          if (frame.current === null) frame.current = requestAnimationFrame(flush); }
      }).catch((error) => { if (!valid()) return; mark(id, "unavailable"); current.current.onError(error, id); });
    }
    return () => { for (const controller of observers.current.values()) controller.abort(); observers.current.clear(); pending.current.clear();
      if (frame.current !== null) cancelAnimationFrame(frame.current); frame.current = null; };
  }, [key, enabled, visible, revision, mark, flush]);
  return { connections, reconnect: () => setRevision((value) => value + 1),
    cancel: async (id) => {
      if (!enabled || !id || mutations.current.has(id) || mutations.current.size >= 4 || !current.current.jobs.some((job) => job.id === id)) return;
      const controller = new AbortController(); mutations.current.set(id, controller); mark(id, "cancel-requested");
      try { const snapshot = await cancelAnalysis(id, { csrfToken: current.current.csrfToken, signal: controller.signal });
        if (!controller.signal.aborted && mounted.current) { current.current.onSnapshot(snapshot); setRevision((value) => value + 1); }
      } catch (error) { if (!controller.signal.aborted && mounted.current) { mark(id, "cancel-unconfirmed"); current.current.onError(error, id); } }
      finally { if (mutations.current.get(id) === controller) mutations.current.delete(id); }
    }
  };
}
