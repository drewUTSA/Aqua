import React from "react";

// Preserve the account owner and its pending revocation on ordinary internal
// navigation. Modified clicks retain the browser's normal new-tab behavior.
export default function LocalLink({ to, onNavigate, children, ...props }) {
  return <a {...props} href={to} onClick={(event) => {
    if (event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      event.preventDefault(); onNavigate(to);
    }
  }}>{children}</a>;
}
