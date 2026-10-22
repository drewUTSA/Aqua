import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import dots from "../../assets/opal/workspace/imgAccountMenuTrigger1.svg";
import ControlIcon from "./ControlIcon.jsx";
export default function AccountMenu({ auth, onNavigate, placement = "below" }) {
  const [open, setOpen] = useState(false);
  const id = useId(), root = useRef(null), trigger = useRef(null), items = useRef([]);
  const close = (restore = false) => { setOpen(false); if (restore) trigger.current?.focus(); };
  useLayoutEffect(() => { if (open) items.current[0]?.focus(); }, [open]);
  useEffect(() => {
    if (!open) return;
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("pointerdown", outside, true);
    document.addEventListener("focusin", outside, true);
    return () => { document.removeEventListener("pointerdown", outside, true); document.removeEventListener("focusin", outside, true); };
  }, [open]);
  const keyboard = (event) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); }
    if (event.key === "Tab") close(true);
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const index = items.current.indexOf(document.activeElement);
      items.current[event.key === "Home" ? 0 : event.key === "End" ? 1 : (index + (event.key === "ArrowDown" ? 1 : -1) + 2) % 2]?.focus();
    }
  };
  return <div className={`account-menu account-menu--${placement}`} ref={root}>
    <button ref={trigger} type="button" className="icon-button" aria-label="Account menu"
      aria-expanded={open} aria-haspopup="menu" aria-controls={open ? id : undefined}
      onClick={() => open ? close(true) : setOpen(true)} onKeyDown={(event) => {
        if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); setOpen(true); }
      }}><ControlIcon asset={dots} /></button>
    {open && <div className="account-menu__panel" role="menu" id={id} aria-label="Your account" onKeyDown={keyboard}>
      <p>{auth.user?.name || auth.user?.email || "Personal workspace"}</p>
      <button type="button" role="menuitem" ref={(element) => { items.current[0] = element; }} onClick={() => { close(); onNavigate("/settings"); }}>Settings</button>
      <button type="button" role="menuitem" ref={(element) => { items.current[1] = element; }} disabled={auth.demoMode}
        onClick={() => { close(); void auth.logout(); }}>Sign out</button>
    </div>}
  </div>;
}
