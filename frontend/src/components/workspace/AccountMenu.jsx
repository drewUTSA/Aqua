import React, { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { leaveMenuWithTab, useMenuSurface } from "../navigation/useMenuSurface.js";
import { moveMenuIndex } from "../navigation/menuPolicy.js";
import "../../styles/menus-refined.css";

function MenuIcon({ kind }) {
  return <svg viewBox="0 0 24 24" aria-hidden="true">{kind === "settings" ? <>
    <path d="m10 3-.6 2.3-2 .9-2.1-.6-2 3.5L5 10.8v2.4l-1.7 1.7 2 3.5 2.1-.6 2 .9L10 21h4l.6-2.3 2-.9 2.1.6 2-3.5-1.7-1.7v-2.4l1.7-1.7-2-3.5-2.1.6-2-.9L14 3Z" />
    <circle cx="12" cy="12" r="3" /></> : <><path d="M10 4H5v16h5M14 8l4 4-4 4M9 12h9" /></>}</svg>;
}

function SignOutConfirmation({ onCancel, onConfirm, trigger }) {
  const dialog = useRef(null), title = useId();
  useLayoutEffect(() => {
    const node = dialog.current;
    node.showModal(); node.querySelector("button")?.focus();
    return () => {
      node.close();
      if (trigger.current?.isConnected && !trigger.current.closest("[hidden],[inert]")) trigger.current.focus({ preventScroll: true });
    };
  }, [trigger]);
  return <dialog ref={dialog} className="account-signout-dialog" aria-labelledby={title}
    onCancel={event => { event.preventDefault(); onCancel(); }}
    onKeyDown={event => {
      if (event.key !== "Tab" || event.ctrlKey || event.metaKey || event.altKey) return;
      const buttons = [...dialog.current.querySelectorAll("button:not(:disabled)")];
      if (!event.shiftKey && document.activeElement === buttons.at(-1) || event.shiftKey && document.activeElement === buttons[0]) {
        event.preventDefault(); buttons[event.shiftKey ? buttons.length - 1 : 0]?.focus();
      }
    }}>
    <span className="account-signout-dialog__eyebrow">Your account</span><h2 id={title}>Sign out of AQUA?</h2>
    <p>Your saved conversations will stay in your account. Unsent drafts in this visit will be cleared after sign-out is confirmed.</p>
    <div><button type="button" onClick={onCancel}>Keep working</button>
      <button type="button" className="account-signout-dialog__confirm" onClick={onConfirm}>Sign out</button></div>
  </dialog>;
}

export default function AccountMenu({ auth, onNavigate, placement = "above" }) {
  const [open, setOpen] = useState(false), [active, setActive] = useState(0), [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  const id = useId(), root = useRef(null), trigger = useRef(null), panel = useRef(null), items = useRef([]);
  const disabledSignOut = auth.demoMode || typeof auth.logout !== "function" || !["authenticated", "logoutfailed"].includes(auth.status);
  const enabled = disabledSignOut ? [0] : [0, 1];
  const close = (restore = false) => { setOpen(false); if (restore) trigger.current?.focus({ preventScroll: true }); };
  const style = useMenuSurface(open, trigger, panel, { width: 280, placement, align: "end", dismiss: close });
  const show = (last = false) => { setActive(last ? enabled.at(-1) : 0); setOpen(true); };
  useLayoutEffect(() => { if (open && style.visibility === "visible") items.current[active]?.focus({ preventScroll: true }); }, [open, active, style.visibility]);
  useEffect(() => {
    if (!open) return undefined;
    const outside = event => { if (!root.current?.contains(event.target)) close(); };
    document.addEventListener("pointerdown", outside, true); document.addEventListener("focusin", outside, true);
    return () => { document.removeEventListener("pointerdown", outside, true); document.removeEventListener("focusin", outside, true); };
  }, [open]);
  useEffect(() => { if (!auth.demoMode && auth.status !== "authenticated") { setOpen(false); setConfirm(false); } }, [auth.status, auth.demoMode]);
  const keyboard = event => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); close(true); return; }
    if (event.key === "Tab") { leaveMenuWithTab(event, trigger, panel, close); return; }
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault(); setActive(moveMenuIndex(event.key, active, enabled));
    }
  };
  const signOut = () => {
    if (disabledSignOut) return;
    setConfirm(false); setError("");
    // The auth owner hides/locks the workspace while awaiting durable server
    // revocation. A returned promise alone never means sign-out succeeded.
    try { Promise.resolve(auth.logout()).catch(() => setError("Sign-out could not be confirmed. Please try again.")); }
    catch { setError("Sign-out could not be confirmed. Please try again."); }
  };
  return <div className={`account-menu account-menu--refined account-menu--${placement}`} ref={root}>
    <button ref={trigger} type="button" className="icon-button account-menu__trigger" aria-label="Account menu"
      aria-expanded={open} aria-haspopup="menu" aria-controls={open ? id : undefined}
      onClick={() => open ? close(true) : show()} onKeyDown={event => {
        if (["ArrowDown", "ArrowUp"].includes(event.key)) { event.preventDefault(); show(event.key === "ArrowUp"); }
      }}><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="5" cy="12" r="1.7" /><circle cx="12" cy="12" r="1.7" /><circle cx="19" cy="12" r="1.7" /></svg></button>
    {open && <div ref={panel} popover="manual" style={style} className="account-menu__panel" role="menu" id={id} aria-label="Your account" onKeyDown={keyboard}>
      <div className="account-menu__identity" role="presentation"><span>{auth.demoMode ? "Demo workspace" : "Personal workspace"}</span>
        <strong>{auth.user?.name || auth.user?.email || "Your account"}</strong>
        {auth.user?.name && auth.user?.email && <p>{auth.user.email}</p>}</div>
      <button type="button" role="menuitem" tabIndex={active === 0 ? 0 : -1} ref={element => { items.current[0] = element; }}
        onFocus={() => setActive(0)} onClick={() => { close(); onNavigate("/settings"); }}><MenuIcon kind="settings" /><span>Settings</span><span className="account-menu__hint" aria-hidden="true">↗</span></button>
      <div className="account-menu__divider" role="separator" />
      <button type="button" role="menuitem" tabIndex={active === 1 ? 0 : -1} ref={element => { items.current[1] = element; }} disabled={disabledSignOut}
        onFocus={() => setActive(1)} onClick={() => { close(); setConfirm(true); }}><MenuIcon kind="signout" /><span>Sign out</span></button>
      {auth.demoMode && <p className="account-menu__demo">Demo changes stay in this visit.</p>}
    </div>}
    {error && <span className="account-menu__error" role="alert">{error}</span>}
    {confirm && <SignOutConfirmation trigger={trigger} onCancel={() => setConfirm(false)} onConfirm={signOut} />}
  </div>;
}
