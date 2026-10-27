import React, { useEffect, useId, useRef } from "react";
import Conversation from "../chat/Conversation.jsx";
import AnalysisStatus from "../chat/AnalysisStatus.jsx";
import mark from "../../assets/opal/workspace/imgAquaConceptMark1.svg";
import globe from "../../assets/opal/workspace/imgIconGlobe.svg";
import arrow from "../../assets/opal/workspace/imgIconArrow.svg";
import chart from "../../assets/opal/workspace/imgIconChart.svg";
import legacyMark from "../../assets/models/AQUA_V2_Final_static.svg?url";

export default function OpalChat({ chat, auth, inputRef, focusRequest, onPrompt, shell = "opal", visible = true, scrollPositions }) {
  const active = chat.messages.length > 0 || (chat.durable && chat.active.messageCount > 0);
  const legacy = shell === "legacy";
  return <main className={`opal-chat${active ? " opal-chat--active" : ""}`}>
    {!active && <header className="opal-welcome"><img src={legacy ? legacyMark : mark} alt="" /><h1 id="workspace-heading" tabIndex={-1}>What would you like to explore?</h1>
      <p>{auth.canQuery ? "Ask about your data. Bring a chart into view when you need one." : "You’re signed in. Ask your AQUA administrator for access to your data."}</p></header>}
    {active && <><h1 id="workspace-heading" className="sr-only" tabIndex={-1}>AQUA workspace</h1>
      {chat.durable && <div className="workspace-history-controls"><button type="button" disabled={chat.pending || chat.active.historyLoading} onClick={chat.refresh}>Refresh saved chat</button>
        {chat.active.olderCursor && <button type="button" disabled={chat.pending || chat.active.historyLoading} onClick={chat.loadOlder}>Load older messages</button>}
        {chat.active.historyLoading && <span role="status">Loading messages…</span>}</div>}
      <Conversation key={chat.activeConversationId} messages={chat.messages} pending={chat.durable ? chat.submitting : chat.pending} waiting={chat.waiting} onRetry={chat.retry} suspended={!visible}
        position={scrollPositions?.get(chat.activeConversationId)} onPositionChange={(position) => scrollPositions?.set(chat.activeConversationId, position)} /></>}
    {chat.durable && !active && chat.active.historyLoading && <p role="status">Loading saved conversation…</p>}
    {chat.durable && chat.uncertain && <div className="workspace-request-notice" role="status"><p>This request may still be processing. Stopping this browser request does not cancel work on the server.</p>
      <button type="button" disabled={chat.pending || !auth.canQuery} onClick={chat.checkSaved}>Check saved request</button></div>}
    {chat.durable && !chat.submitting && <AnalysisStatus request={chat.analysis} connection={chat.analysisConnection} onReconnect={chat.reconnectAnalysis} />}
    <Composer chat={chat} auth={auth} inputRef={inputRef} focusRequest={focusRequest} active={active} />
    {!legacy && !active && auth.canQuery && <div className="opal-suggestions" aria-label="Suggested starting points">
      {chat.faqs.slice(0, 3).map((faq) =>
        <button type="button" key={faq.id} onClick={() => onPrompt(faq.prompt)}><span><img src={chart} alt="" />{faq.title}</span><small>Use this starter question.</small></button>)}
    </div>}
    <p className="opal-disclaimer">Check important figures against your source.</p>
  </main>;
}

function Composer({ chat, auth, inputRef, focusRequest, active }) {
  const ownRef = useRef(null), id = useId();
  const textarea = inputRef || ownRef;
  useEffect(() => { if (focusRequest) textarea.current?.focus({ preventScroll: true }); }, [focusRequest, textarea]);
  const allowed = auth.canQuery && !!chat.draft.trim() && !chat.pending && !chat.uncertain && !chat.active?.archived && (!chat.durable || !!chat.selectedModelId);
  const serverPending = chat.durable && chat.pending && !chat.submitting;
  const stop = serverPending ? chat.cancelAnalysis : chat.stop;
  const stopLabel = serverPending ? chat.analysis?.cancelRequested || chat.analysis?.state === "cancelling" ? "Cancellation requested" : "Cancel analysis" : "Stop response";
  return <div className="opal-composer-wrap"><form className="opal-composer" aria-label="Ask AQUA" method="post" action="/api/query"
    onSubmit={(event) => { event.preventDefault(); if (allowed) chat.submit(chat.draft); }}>
    <label className="sr-only" htmlFor={id}>Ask AQUA about your financial data</label>
    <textarea ref={textarea} id={id} rows={2} value={chat.draft} maxLength={auth.demoMode ? 10000 : 2000}
      disabled={!auth.canQuery} placeholder="Ask a question about your financial data…" aria-describedby={`${id}-hint`}
      onChange={(event) => chat.setDraft(event.target.value)} onKeyDown={(event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
          event.preventDefault(); event.currentTarget.form.requestSubmit();
        }
      }} />
    <div className="opal-composer__toolbar"><span><img src={globe} alt="" />{auth.demoMode ? "Fictional sample data" : "Authorized data only"}</span>
      <label className="mobile-model"><span className="sr-only">AI model</span><select aria-label="AI model" value={chat.selectedModelId}
        disabled={!auth.canQuery || !chat.models.length} onChange={(event) => chat.setModelId(event.target.value)}>
        {chat.models.map((model) => <option key={model.id} value={model.id}>{model.name}</option>)}
      </select></label>
      <button className="opal-send" type={chat.pending ? "button" : "submit"} disabled={chat.pending ? !auth.canQuery || !stop : !allowed}
        aria-label={chat.pending ? stopLabel : "Send message"} title={chat.pending ? stopLabel : "Send message"}
        onClick={chat.pending ? stop : undefined}>{chat.pending ? <span className="opal-stop" aria-hidden="true" /> : <><img src={arrow} alt="" /><span className="opal-send__contrast-icon" aria-hidden="true" style={{ maskImage: `url("${arrow}")` }} /></>}</button></div>
  </form><p className="composer-hint" id={`${id}-hint`}>{!auth.canQuery ? "Data access is pending approval." : chat.active?.archived ? "Restore this archived chat before sending another question."
    : serverPending ? "Analysis continues on the server. Cancellation is confirmed by saved status."
      : `${chat.pending ? "Stop ends this browser’s wait; server work may continue. " : ""}Enter to ${active ? "send" : "ask"} · Shift + Enter for a new line`}</p></div>;
}
