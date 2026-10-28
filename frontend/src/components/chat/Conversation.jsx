import React, { useEffect, useLayoutEffect, useRef, useState } from "react";
import AquaMessage from "./AquaMessage.jsx";
import UserMessage from "./UserMessage.jsx";

export default function Conversation({ messages, pending, waiting, preferences, formingIds = [], onRetry, onShowVisual, suspended = false, position, onPositionChange }) {
  const follow = preferences?.device.auto_scroll !== "manual";
  const [essentialError, setEssentialError] = useState("");
  const knownStatuses = useRef(new Map(messages.map((message) => [message.id, message.response?.status || message.status])));
  const priorPending = useRef(pending);
  useEffect(() => {
    // Optional streaming chatter can be reduced. Newly failed requests still
    // announce their action; opening old history must not replay its errors.
    for (const message of messages) {
      const status = message.response?.status, previous = knownStatuses.current.get(message.id);
      if (status === "error" && (previous === "loading" || previous === "pending" || priorPending.current && !knownStatuses.current.has(message.id))) {
        setEssentialError(message.response.error?.message || "AQUA could not complete that request. Check the conversation for details.");
      }
    }
    knownStatuses.current = new Map(messages.map((message) => [message.id, message.response?.status || message.status]));
    if (pending && !priorPending.current) setEssentialError("");
    priorPending.current = pending;
  }, [messages, pending]);
  const scrollerRef = useRef(null);
  const nearBottomRef = useRef(position?.nearBottom ?? true);
  const scrollPositionRef = useRef(position?.top ?? 0);
  const previousLayout = useRef(null);
  const visible = (node) => node && !suspended && node.getClientRects().length > 0 && node.clientHeight > 0 && !node.closest("[hidden],[inert]");

  const updateNearBottom = () => {
    const node = scrollerRef.current;
    // Hidden panels report zero dimensions. They must not convert an older
    // reading position into "follow newest" while visiting Settings or policies.
    if (!visible(node)) return;
    scrollPositionRef.current = node.scrollTop;
    if (previousLayout.current) previousLayout.current = { ...previousLayout.current, top: node.scrollTop, height: node.scrollHeight };
    nearBottomRef.current = node.scrollHeight - node.scrollTop - node.clientHeight < 120;
    onPositionChange?.({ top: scrollPositionRef.current, nearBottom: nearBottomRef.current });
  };

  useLayoutEffect(() => {
    const node = scrollerRef.current;
    if (visible(node)) node.scrollTop = follow && nearBottomRef.current ? node.scrollHeight : scrollPositionRef.current;
  }, [suspended]);
  useLayoutEffect(() => {
    const node = scrollerRef.current, previous = previousLayout.current;
    if (!visible(node)) return;
    if (previous && Number.isSafeInteger(messages[0]?.sequence) && messages[0].sequence < previous.firstSequence) {
      node.scrollTop = previous.top + node.scrollHeight - previous.height;
      nearBottomRef.current = false; scrollPositionRef.current = node.scrollTop;
    } else if (!nearBottomRef.current) node.scrollTop = scrollPositionRef.current;
    previousLayout.current = { height: node.scrollHeight, top: node.scrollTop, firstSequence: messages[0]?.sequence };
  }, [messages, suspended]);

  useEffect(() => {
    const node = scrollerRef.current;
    if (!visible(node)) return undefined;
    if (follow && nearBottomRef.current) node.scrollTop = node.scrollHeight;
    const observer = new ResizeObserver(() => {
      if (visible(node) && follow && nearBottomRef.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(node.querySelector(".conversation__messages") || node);
    return () => observer.disconnect();
  }, [messages, pending, suspended, follow]);

  return (
    <section className="conversation" aria-label="Conversation">
      <p className="sr-only" role="alert" aria-atomic="true">{essentialError}</p>
      <div
        className="conversation__scroll"
        ref={scrollerRef}
        onScroll={updateNearBottom}
        role="log"
        aria-live={preferences?.device.announcements === "reduced" ? "off" : "polite"}
        aria-label="AQUA conversation"
        aria-relevant="additions text"
      >
        <div className="conversation__messages">
          {messages.map((message) => message.role === "user"
            ? <UserMessage key={message.id} message={message} hidden={formingIds.includes(message.id)} />
            : <AquaMessage
                key={message.id}
                message={message}
                preferences={preferences}
                hidden={formingIds.includes(message.id)}
                onRetry={onRetry}
                onShowVisual={onShowVisual}
              />)}
          {pending && (
            <p className="processing-status" role="status" aria-live="polite">
              <span aria-hidden="true" />{waiting ? "AQUA is exploring your numbers" : "AQUA is preparing your answer"}
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
