import React, { useEffect, useRef, useState } from "react";
import OpalChat from "./OpalChat.jsx";
import VisualPane from "./VisualPane.jsx";
import { useVisualResults } from "../../hooks/useVisualResults.js";
import "../../styles/visual-workspace.css";

const PREF = "aqua.visuals.conversation-width";
const readWidth = () => { try { const value = Number(localStorage.getItem(PREF)); return value >= 28 && value <= 65 ? value : 38; } catch { return 38; } };
export default function VisualWorkspace({ chat, auth, visible, preferences, onDeviceChange, chartTheme, ...props }) {
  const allowed = auth.demoMode || auth.session?.can_query === true;
  const visuals = useVisualResults(chat, allowed, preferences?.account.initial_result_view);
  const container = useRef(null), dragging = useRef(false);
  const [width, setWidth] = useState(readWidth), [space, setSpace] = useState(0);
  useEffect(() => { if (preferences) setWidth(preferences.device.split_percent); }, [preferences?.device.split_percent]);
  useEffect(() => { const observer = new ResizeObserver(([entry]) => setSpace(entry.contentRect.width)); observer.observe(container.current); return () => observer.disconnect(); }, []);
  const mobile = space < 800;
  const limits = { min: Math.max(28, 320 / Math.max(space - 16, 1) * 100), max: Math.min(65, 100 - 360 / Math.max(space - 16, 1) * 100) };
  const actual = Math.min(limits.max, Math.max(limits.min, width));
  const resize = (value) => { const next = Math.round(Math.min(limits.max, Math.max(limits.min, value))); setWidth(next);
    if (onDeviceChange) onDeviceChange("split_percent", next);
    else try { localStorage.setItem(PREF, String(next)); } catch { /* Standalone fallback keeps the divider usable without storage. */ } };
  const split = visuals.open && !mobile && !visuals.view.expanded;
  const visualTab = mobile && visuals.open && visuals.view.tab === "visuals";
  const close = () => { visuals.close(); requestAnimationFrame(() => {
    if (!container.current?.isConnected) return;
    const button = container.current.querySelector(`[data-message-id="${CSS.escape(visuals.selected?.id || "")}"] .visual-result-open`);
    (button || props.inputRef?.current)?.focus({ preventScroll: true });
  }); };
  return <div ref={container} className={`visual-workspace${visuals.open ? " visual-workspace--open" : ""}${mobile ? " visual-workspace--mobile" : ""}${visuals.view.expanded && visuals.open && !mobile ? " visual-workspace--expanded" : ""}${visualTab ? " visual-workspace--visual-tab" : ""}`}
    style={split ? { gridTemplateColumns: `minmax(320px, ${Math.floor((space - 16) * actual / 100)}px) 16px minmax(360px, 1fr)` } : undefined}>
    {mobile && visuals.open && <div className="visual-workspace__tabs" role="group" aria-label="Workspace view">
      <button type="button" aria-pressed={!visualTab} onClick={() => visuals.change((previous) => ({ ...previous, tab: "conversation" }))}>Conversation</button>
      <button type="button" aria-pressed={visualTab} onClick={() => visuals.change((previous) => ({ ...previous, tab: "visuals" }))}>Visuals</button>
      {visuals.result && !visuals.view.pending && <span role="status">Visual ready</span>}</div>}
    <OpalChat {...props} chat={visuals.chat} auth={auth} preferences={preferences} visible={visible && !visualTab && !(visuals.open && visuals.view.expanded && !mobile)}
      onShowVisual={visuals.show} visualsHidden={visualTab || visuals.open && visuals.view.expanded && !mobile} />
    {split && <div className="visual-divider" role="separator" aria-label="Conversation and visuals width" aria-orientation="vertical" tabIndex={0}
      aria-valuemin={Math.round(limits.min)} aria-valuemax={Math.round(limits.max)} aria-valuenow={Math.round(actual)} aria-valuetext={`${Math.round(actual)} percent conversation`}
      onKeyDown={(event) => { const value = { ArrowLeft: actual - (event.shiftKey ? 10 : 2), ArrowRight: actual + (event.shiftKey ? 10 : 2), Home: limits.min, End: limits.max }[event.key];
        if (value !== undefined) { event.preventDefault(); resize(value); } }}
      onPointerDown={(event) => { dragging.current = true; event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => { if (dragging.current) resize((event.clientX - container.current.getBoundingClientRect().left) / (space - 16) * 100); }}
      onPointerUp={() => { dragging.current = false; }} onPointerCancel={() => { dragging.current = false; }} onLostPointerCapture={() => { dragging.current = false; }} />}
    {visuals.open && <VisualPane key={chat.active?.viewId || chat.activeConversationId} visuals={{ ...visuals, close }} shell={props.shell} canExpand={!mobile}
      owner={chat.active?.viewId || chat.activeConversationId} preferences={preferences} chartTheme={chartTheme} hidden={mobile && !visualTab} suspended={!visible} />}
  </div>;
}
