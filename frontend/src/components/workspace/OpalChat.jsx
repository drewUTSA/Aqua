import React, { useEffect, useId, useRef } from "react";
import Conversation from "../chat/Conversation.jsx";
import mark from "../../assets/opal/workspace/imgAquaConceptMark1.svg";
import globe from "../../assets/opal/workspace/imgIconGlobe.svg";
import arrow from "../../assets/opal/workspace/imgIconArrow.svg";
import chart from "../../assets/opal/workspace/imgIconChart.svg";
import legacyMark from "../../assets/models/AQUA_V2_Final_static.svg?url";

export default function OpalChat({ chat, auth, inputRef, focusRequest, onPrompt, shell = "opal", visible = true }) {
  const active = chat.messages.length > 0;
  const legacy = shell === "legacy";
  return <main className={`opal-chat${active ? " opal-chat--active" : ""}`}>
    {!active && <header className="opal-welcome"><img src={legacy ? legacyMark : mark} alt="" /><h1 id="workspace-heading" tabIndex={-1}>What would you like to explore?</h1>
      <p>{auth.canQuery ? "Ask about your data. Bring a chart into view when you need one." : "You’re signed in. Ask your AQUA administrator for access to your data."}</p></header>}
    {active && <><h1 id="workspace-heading" className="sr-only" tabIndex={-1}>AQUA workspace</h1>
      <Conversation key={chat.activeConversationId} messages={chat.messages} pending={chat.pending} waiting={chat.waiting} onRetry={chat.retry} suspended={!visible} /></>}
    <Composer chat={chat} auth={auth} inputRef={inputRef} focusRequest={focusRequest} active={active} />
    {!legacy && !active && auth.canQuery && <div className="opal-suggestions" aria-label="Suggested starting points">
      {[[0, "Loan performance", "Review balances and repayment trends."], [2, "Compare districts", "Find patterns across your districts."], [3, "Account growth", "Explore accounts opened over time."]].map(([index, title, detail]) =>
        <button type="button" key={title} onClick={() => onPrompt(chat.faqs[index].prompt)}><span><img src={chart} alt="" />{title}</span><small>{detail}</small></button>)}
    </div>}
    <p className="opal-disclaimer">Check important figures against your source.</p>
  </main>;
}

function Composer({ chat, auth, inputRef, focusRequest, active }) {
  const ownRef = useRef(null), id = useId();
  const textarea = inputRef || ownRef;
  useEffect(() => { if (focusRequest) textarea.current?.focus({ preventScroll: true }); }, [focusRequest, textarea]);
  const allowed = auth.canQuery && !!chat.draft.trim() && !chat.pending;
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
      <button className="opal-send" type={chat.pending ? "button" : "submit"} disabled={chat.pending ? !auth.canQuery : !allowed}
        aria-label={chat.pending ? "Stop response" : "Send message"} title={chat.pending ? "Stop response" : "Send message"}
        onClick={chat.pending ? chat.stop : undefined}>{chat.pending ? <span className="opal-stop" aria-hidden="true" /> : <><img src={arrow} alt="" /><span className="opal-send__contrast-icon" aria-hidden="true" style={{ maskImage: `url("${arrow}")` }} /></>}</button></div>
  </form><p className="composer-hint" id={`${id}-hint`}>{!auth.canQuery ? "Data access is pending approval." : `${chat.pending ? "Stop ends this browser’s request. " : ""}Enter to ${active ? "send" : "ask"} · Shift + Enter for a new line`}</p></div>;
}
