import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import Conversation from "../chat/Conversation.jsx";
import AnalysisStatus from "../chat/AnalysisStatus.jsx";
import mark from "../../assets/opal/workspace/imgAquaConceptMark1.svg";
import arrow from "../../assets/opal/workspace/imgIconArrow.svg";
import legacyMark from "../../assets/models/AQUA_V2_Final_static.svg?url";
import ModelSelector from "../navigation/ModelSelector.jsx";
import { leaveMenuWithTab, useMenuSurface } from "../navigation/useMenuSurface.js";
import { useReducedMotion } from "../../hooks/useReducedMotion.js";

export default function OpalChat({ chat, auth, inputRef, focusRequest, onOpenPrompts, preferences, shell = "opal", visible = true, scrollPositions, onShowVisual, visualsHidden = false }) {
  const active = chat.messages.length > 0 || (chat.durable && chat.active.messageCount > 0);
  const legacy = shell === "legacy";
  return <main className={`opal-chat${active ? " opal-chat--active" : ""}${visualsHidden ? " opal-chat--visual-hidden" : ""}`}>
    {!active && <header className="opal-welcome"><img src={legacy ? legacyMark : mark} alt="" /><h1 id="workspace-heading" tabIndex={-1}>What would you like to explore?</h1>
      <p>{auth.canQuery ? "Ask about your data. Bring a chart into view when you need one." : "You’re signed in. Ask your AQUA administrator for access to your data."}</p></header>}
    {active && <><h1 id="workspace-heading" className="sr-only" tabIndex={-1}>AQUA workspace</h1>
      {chat.durable && <div className="workspace-history-controls"><ConversationActions chat={chat} />
        {chat.active.olderCursor && <button type="button" disabled={chat.pending || chat.active.historyLoading} onClick={chat.loadOlder}>Load older messages</button>}
        {chat.active.historyLoading && <span role="status">Loading messages…</span>}</div>}
      <Conversation key={chat.active?.viewId || chat.activeConversationId} messages={chat.messages} preferences={preferences} pending={chat.durable ? chat.submitting : chat.pending} waiting={chat.waiting} onRetry={chat.retry} onShowVisual={onShowVisual} suspended={!visible}
        position={scrollPositions?.get(chat.activeConversationId)} onPositionChange={(position) => scrollPositions?.set(chat.activeConversationId, position)} /></>}
    {chat.durable && !active && chat.active.historyLoading && <p role="status">Loading saved conversation…</p>}
    {chat.durable && chat.uncertain && <div className="workspace-request-notice" role="status"><p>This request may still be processing. Stopping this browser request does not cancel work on the server.</p>
      <button type="button" disabled={chat.pending || !auth.canQuery} onClick={chat.checkSaved}>Check saved request</button></div>}
    {chat.durable && !chat.submitting && <AnalysisStatus request={chat.analysis} connection={chat.analysisConnection} onReconnect={chat.reconnectAnalysis} />}
    <Composer chat={chat} auth={auth} preferences={preferences} inputRef={inputRef} focusRequest={focusRequest} active={active} visible={visible} onOpenPrompts={onOpenPrompts} />
    <p className="opal-disclaimer">Check important figures against your source.</p>
  </main>;
}

function Composer({ chat, auth, preferences, inputRef, focusRequest, active, visible, onOpenPrompts }) {
  const ownRef = useRef(null), wrap = useRef(null), previous = useRef(null), animation = useRef(null), id = useId();
  const textarea = inputRef || ownRef;
  const reduced = useReducedMotion() || preferences?.device.motion === "reduce";
  useEffect(() => { if (focusRequest) textarea.current?.focus({ preventScroll: true }); }, [focusRequest, textarea]);
  useLayoutEffect(() => {
    const node = textarea.current;
    if (!node || !visible) return;
    node.style.height = "auto";
    node.style.height = `${Math.min(Math.max(node.scrollHeight, active ? 28 : 72), Math.min(220, innerHeight * .32))}px`;
  }, [chat.draft, active, visible, preferences?.device.text_scale, textarea]);
  useLayoutEffect(() => {
    const node = wrap.current;
    if (!node || !visible) { previous.current = null; animation.current?.cancel(); return; }
    const rect = node.getBoundingClientRect(), before = previous.current;
    animation.current?.cancel();
    // Move the same form between welcome and conversation. Never remount the
    // textarea: IME composition, selection and per-chat drafts remain intact.
    if (!reduced && before && before.active !== active && node.animate) {
      animation.current = node.animate([{ transform: `translateY(${before.top - rect.top}px)` }, { transform: "translateY(0)" }],
        { duration: 260, easing: "cubic-bezier(.2,.8,.2,1)" });
    }
    previous.current = { top: rect.top, active };
  }, [active, visible, reduced]);
  useEffect(() => () => animation.current?.cancel(), []);
  const allowed = auth.canQuery && !!chat.draft.trim() && !chat.pending && !chat.uncertain && !chat.active?.archived && (!chat.durable || !!chat.selectedModelId);
  const serverPending = chat.durable && chat.pending && !chat.submitting;
  const stop = serverPending ? chat.cancelAnalysis : chat.stop;
  const stopLabel = serverPending ? chat.analysis?.cancelRequested || chat.analysis?.state === "cancelling" ? "Cancellation requested" : "Cancel analysis" : "Stop response";
  return <div ref={wrap} className="opal-composer-wrap"><form className="opal-composer" aria-label="Ask AQUA" method="post" action="/api/query"
    onSubmit={(event) => { event.preventDefault(); if (allowed) chat.submit(chat.draft); }}>
    <label className="sr-only" htmlFor={id}>Ask AQUA about your financial data</label>
    <textarea ref={textarea} id={id} rows={active ? 1 : 2} value={chat.draft} maxLength={auth.demoMode ? 10000 : 2000}
      disabled={!auth.canQuery} placeholder="Ask a question about your financial data…" aria-describedby={`${id}-hint`}
      onChange={(event) => chat.setDraft(event.target.value)} onKeyDown={(event) => {
        const modified = preferences?.device.send_shortcut === "modified_enter";
        if (event.key === "Enter" && !event.shiftKey && (modified ? event.ctrlKey || event.metaKey : !event.ctrlKey && !event.metaKey) && !event.nativeEvent.isComposing && event.keyCode !== 229) {
          event.preventDefault(); event.currentTarget.form.requestSubmit();
        }
      }} />
    <div className="opal-composer__toolbar"><ModelSelector models={chat.models} selectedModelId={chat.selectedModelId} onSelectModel={chat.setModelId} disabled={!auth.canQuery} />
      <button type="button" className="composer-prompts" aria-label="Saved prompts" aria-haspopup="dialog" onClick={onOpenPrompts}>
        <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M7 4h10v16l-5-3-5 3Z" /></svg>
      </button>
      <button className="opal-send" type={chat.pending ? "button" : "submit"} disabled={chat.pending ? !auth.canQuery || !stop : !allowed}
        aria-label={chat.pending ? stopLabel : "Send message"} title={chat.pending ? stopLabel : "Send message"}
        onClick={chat.pending ? stop : undefined}>{chat.pending ? <span className="opal-stop" aria-hidden="true" /> : <><img src={arrow} alt="" /><span className="opal-send__contrast-icon" aria-hidden="true" style={{ maskImage: `url("${arrow}")` }} /></>}</button></div>
  </form><p className="composer-hint" id={`${id}-hint`}>{!auth.canQuery ? "Data access is pending approval." : chat.active?.archived ? "Restore this archived chat before sending another question."
    : serverPending ? "Analysis continues on the server. Cancellation is confirmed by saved status."
      : `${chat.pending ? "Stop ends this browser’s wait; server work may continue. " : ""}${preferences?.device.send_shortcut === "modified_enter" ? "Ctrl/Cmd + Enter" : "Enter"} to ${active ? "send" : "ask"} · ${preferences?.device.send_shortcut === "modified_enter" ? "Enter" : "Shift + Enter"} for a new line`}</p></div>;
}

function ConversationActions({ chat }) {
  const [open, setOpen] = useState(false), root = useRef(null), trigger = useRef(null), panel = useRef(null), action = useRef(null), id = useId();
  const close = (restore = false) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); };
  const style = useMenuSurface(open, trigger, panel, { width: 240, placement: "below", align: "end", dismiss: close });
  useLayoutEffect(() => { if (open && style.visibility === "visible") action.current?.focus({ preventScroll: true }); }, [open, style.visibility]);
  useEffect(() => {
    if (!open) return;
    const outside = (event) => { if (!root.current?.contains(event.target)) close(); };
    document.addEventListener("pointerdown", outside, true); document.addEventListener("focusin", outside, true);
    return () => { document.removeEventListener("pointerdown", outside, true); document.removeEventListener("focusin", outside, true); };
  }, [open]);
  return <div ref={root} className="conversation-actions"><button ref={trigger} type="button" aria-label="Conversation options" aria-haspopup="menu" aria-expanded={open} aria-controls={open ? id : undefined}
    onClick={() => open ? close(true) : setOpen(true)} onKeyDown={(event) => { if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); setOpen(true); } }}>···</button>
    {open && <div ref={panel} id={id} role="menu" aria-label="Conversation actions" popover="manual" style={style} onKeyDown={(event) => {
      if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
      else if (event.key === "Tab" && !event.ctrlKey && !event.metaKey && !event.altKey) leaveMenuWithTab(event, trigger, panel, close);
      else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) { event.preventDefault(); action.current?.focus(); }
    }}><button ref={action} type="button" role="menuitem" disabled={chat.pending || chat.active.historyLoading} onClick={() => { chat.refresh(); close(true); }}>Refresh conversation</button></div>}
  </div>;
}
