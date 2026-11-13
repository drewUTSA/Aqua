// Optional cross-tab coordination cannot be a prerequisite for signing in.
export function attachAuthBrowserEvents({ onRefresh, onLock, onOffline, canRefresh = () => true,
  target = globalThis.window, page = globalThis.document, Channel, now = () => Date.now() }) {
  let channel = null, disposed = false, checked = now(), needsRefresh = false;
  const closeChannel = () => {
    try { if (channel) channel.onmessage = null; } catch { /* Optional storage may be denied. */ }
    try { channel?.close(); } catch { /* A suspended browser may already close it. */ }
    channel = null;
  };
  try {
    const Factory = Channel === undefined ? globalThis.BroadcastChannel : Channel;
    if (typeof Factory === "function") {
      channel = new Factory("aqua-session-events");
      channel.onmessage = ({ data }) => {
        if (disposed || !data || typeof data !== "object" || Array.isArray(data) || Object.keys(data).length !== 1) return;
        if (data.type === "changed") onRefresh({ sessionChanged: true });
        if (data.type === "locked") onLock();
      };
    }
  } catch { closeChannel(); }
  const recheck = (force = false) => {
    if (disposed) return;
    if (page.visibilityState !== "visible") { if (force) needsRefresh = true; return; }
    const elapsed = now() - checked;
    if (!force && !needsRefresh && (!canRefresh() || (elapsed >= 0 && elapsed < 10000))) return;
    checked = now(); needsRefresh = false;
    onRefresh();
  };
  const foreground = () => recheck();
  const restored = (event) => { if (event.persisted) recheck(true); };
  const online = () => recheck(true);
  const offline = () => { if (!disposed) onOffline?.(); };
  target.addEventListener("focus", foreground);
  page.addEventListener("visibilitychange", foreground);
  target.addEventListener("pageshow", restored);
  target.addEventListener("online", online);
  target.addEventListener("offline", offline);
  return {
    notify(type = "changed") {
      if (disposed || !["changed", "locked"].includes(type)) return;
      try { channel?.postMessage({ type }); } catch { closeChannel(); }
    },
    dispose() {
      if (disposed) return;
      disposed = true; closeChannel();
      target.removeEventListener("focus", foreground);
      page.removeEventListener("visibilitychange", foreground);
      target.removeEventListener("pageshow", restored);
      target.removeEventListener("online", online);
      target.removeEventListener("offline", offline);
    }
  };
}

export const AUTH_DEADLINE_MS = 30000;
export function authDeadline(controller, isCurrent, onTimeout) {
  let active = true;
  const timer = setTimeout(() => {
    if (!active || controller.signal.aborted || !isCurrent()) return;
    active = false; controller.abort(); onTimeout();
  }, AUTH_DEADLINE_MS);
  return () => { active = false; clearTimeout(timer); };
}
