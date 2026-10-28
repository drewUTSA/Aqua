import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { leaveMenuWithTab, useMenuSurface } from "../navigation/useMenuSurface.js";

// A nested manual popover avoids scroll clipping without leaving the current
// account or mobile navigation dialog's inert/focus scope.
export default function SidebarActionMenu({ label, items }) {
  const [open, setOpen] = useState(false);
  const root = useRef(null), trigger = useRef(null), panel = useRef(null), first = useRef(false), id = useId();
  const close = (restore = false) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); };
  const style = useMenuSurface(open, trigger, panel, { width: 240, placement: "below", align: "end", dismiss: close });
  useLayoutEffect(() => {
    if (!open || !panel.current || style.visibility !== "visible") return;
    const controls = [...panel.current.querySelectorAll('[role="menuitem"]')].filter((node) => !node.disabled);
    controls[first.current ? controls.length - 1 : 0]?.focus({ preventScroll: true });
  }, [open, style.visibility]);
  useEffect(() => {
    if (!open) return;
    const outside = (event) => { if (!root.current?.contains(event.target)) close(); };
    document.addEventListener("pointerdown", outside, true); document.addEventListener("focusin", outside, true);
    return () => { document.removeEventListener("pointerdown", outside, true); document.removeEventListener("focusin", outside, true); };
  }, [open]);
  const keyboard = (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
    else if (event.key === "Tab" && !event.ctrlKey && !event.metaKey && !event.altKey) leaveMenuWithTab(event, trigger, panel, close);
    else if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const controls = [...panel.current.querySelectorAll('[role="menuitem"]')].filter((node) => !node.disabled);
      const index = controls.indexOf(document.activeElement);
      controls[event.key === "Home" ? 0 : event.key === "End" ? controls.length - 1
        : (index + (event.key === "ArrowDown" ? 1 : -1) + controls.length) % controls.length]?.focus();
    }
  };
  return <div ref={root} className="refined-row-menu">
    <button ref={trigger} type="button" className="refined-row-actions" disabled={items.every((item) => item.disabled)} aria-label={label} aria-haspopup="menu"
      aria-expanded={open} aria-controls={open ? id : undefined} onClick={() => { first.current = false; setOpen((value) => !value); }}
      onKeyDown={(event) => { if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault(); first.current = event.key === "ArrowUp"; setOpen(true);
      } }}> <span aria-hidden="true">···</span></button>
    {open && <div ref={panel} popover="manual" id={id} role="menu" aria-label={label} className="refined-action-menu" style={style} onKeyDown={keyboard}>
      {items.map((item) => <button key={item.key} role="menuitem" type="button" disabled={item.disabled} data-danger={item.danger || undefined}
        onClick={() => { close(true); item.action(); }}>{item.label}</button>)}
    </div>}
  </div>;
}
