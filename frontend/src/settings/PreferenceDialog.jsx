import React, { useEffect, useId, useRef } from "react";

export default function PreferenceDialog({ title, children, onClose, busy = false, className = "" }) {
  const ref = useRef(null), heading = useId();
  useEffect(() => {
    const trigger = document.activeElement, node = ref.current;
    // The navigation guard's dialog is a sibling of the workspace. Copy only
    // our finite theme tokens so its preview matches the invoking surface.
    if (trigger && node) {
      const computed = getComputedStyle(trigger);
      for (const token of ["bg", "panel", "raised", "text", "muted", "border", "accent", "on-accent", "danger"]) {
        const value = computed.getPropertyValue(`--pref-${token}`);
        if (value) node.style.setProperty(`--pref-${token}`, value);
      }
    }
    node?.showModal();
    return () => { node?.close(); if (trigger?.isConnected) trigger.focus({ preventScroll: true }); };
  }, []);
  const keyboard = (event) => {
    if (event.key !== "Tab" || event.ctrlKey || event.metaKey || event.altKey) return;
    const node = ref.current;
    if (!node) return;
    const focusable = [...node.querySelectorAll("button,input,select,textarea,a[href],[tabindex],[contenteditable=true]")]
      .filter((element) => element.tabIndex >= 0 && !element.matches(":disabled") && !element.closest("[hidden],[inert]")
        && element.getClientRects().length > 0 && !["hidden", "collapse"].includes(getComputedStyle(element).visibility));
    if (!focusable.length) { event.preventDefault(); node.focus({ preventScroll: true }); return; }
    const index = focusable.indexOf(document.activeElement);
    // Native modal focus may otherwise cross into browser chrome at a boundary.
    // Wrap only ordinary Tab; browser and assistive-technology chords retain it.
    if (index === -1 || event.shiftKey && index === 0 || !event.shiftKey && index === focusable.length - 1) {
      event.preventDefault(); focusable[event.shiftKey ? focusable.length - 1 : 0].focus({ preventScroll: true });
    }
  };
  return <dialog ref={ref} tabIndex={-1} className={`preference-dialog ${className}`} aria-labelledby={heading} onKeyDown={keyboard}
    onCancel={(event) => { event.preventDefault(); if (!busy) onClose(); }}>
    <h2 id={heading}>{title}</h2>{children}
  </dialog>;
}
