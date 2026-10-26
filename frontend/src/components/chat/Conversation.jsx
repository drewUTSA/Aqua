import React, { useEffect, useLayoutEffect, useRef } from "react";
import AquaMessage from "./AquaMessage.jsx";
import UserMessage from "./UserMessage.jsx";

export default function Conversation({ messages, pending, waiting, formingIds = [], onRetry, suspended = false, position, onPositionChange }) {
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
    if (visible(node)) node.scrollTop = nearBottomRef.current ? node.scrollHeight : scrollPositionRef.current;
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
    if (nearBottomRef.current) node.scrollTop = node.scrollHeight;
    const observer = new ResizeObserver(() => {
      if (visible(node) && nearBottomRef.current) node.scrollTop = node.scrollHeight;
    });
    observer.observe(node.querySelector(".conversation__messages") || node);
    return () => observer.disconnect();
  }, [messages, pending, suspended]);

  return (
    <section className="conversation" aria-label="Conversation">
      <div
        className="conversation__scroll"
        ref={scrollerRef}
        onScroll={updateNearBottom}
        role="log"
        aria-label="AQUA conversation"
        aria-relevant="additions text"
      >
        <div className="conversation__messages">
          {messages.map((message) => message.role === "user"
            ? <UserMessage key={message.id} message={message} hidden={formingIds.includes(message.id)} />
            : <AquaMessage
                key={message.id}
                message={message}
                hidden={formingIds.includes(message.id)}
                onRetry={onRetry}
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
