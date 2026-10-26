import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useChat } from "../../hooks/useChat.js";
import { useWorkspace } from "../../hooks/useWorkspace.js";
import ModelSelector from "../navigation/ModelSelector.jsx";
import OpalSidebar from "./OpalSidebar.jsx";
import OpalChat from "./OpalChat.jsx";
import AccountMenu from "./AccountMenu.jsx";
import SettingsShell from "../../pages/SettingsShell.jsx";
import OpalBackdrop from "../auth/OpalBackdrop.jsx";
import plus from "../../assets/opal/workspace/imgIconPlus.svg";
import ControlIcon from "./ControlIcon.jsx";
import { UI_SHELL } from "../../services/runtimeConfig.js";
import "../../styles/workspace.css";
import "../../styles/legacy-workspace.css";
import "../../styles/workspace-library.css";

export default function Workspace({ auth, hidden, path, onNavigate }) {
  return auth.demoMode ? <DemoWorkspace auth={auth} hidden={hidden} path={path} onNavigate={onNavigate} />
    : <LiveWorkspace auth={auth} hidden={hidden} path={path} onNavigate={onNavigate} />;
}
function DemoWorkspace(props) {
  const { auth } = props;
  const chat = useChat({ demoMode: auth.demoMode, canQuery: auth.canQuery, csrfToken: auth.csrfToken, onAuthFailure: auth.refresh });
  return <WorkspaceView {...props} chat={chat} />;
}
function LiveWorkspace(props) {
  const { auth, hidden } = props;
  const chat = useWorkspace({ canQuery: auth.canQuery, canReadResults: auth.session?.can_query === true,
    csrfToken: auth.csrfToken, onAuthFailure: auth.refresh, suspended: hidden });
  return <WorkspaceView {...props} chat={chat} />;
}
function WorkspaceView({ auth, hidden, path, onNavigate, chat }) {
  const [sidebar, setSidebar] = useState(true), [drawer, setDrawer] = useState(false), [focus, setFocus] = useState(0);
  const [notice, setNotice] = useState("");
  const inputRef = useRef(null), dialogRef = useRef(null), navigationRef = useRef(null);
  const scrollPositions = useRef(new Map());
  const settings = path === "/settings";
  const caption = settings ? "Settings" : chat.durable && chat.active?.revision ? chat.active.title : "New chat";
  const focusComposer = useCallback(() => setFocus((value) => value + 1), []);
  const closeDrawer = () => { dialogRef.current?.close(); setDrawer(false); navigationRef.current?.focus(); };
  const go = (target) => { closeDrawer(); onNavigate(target); };
  const start = () => {
    if (!chat.startConversation()) setNotice("You have reached the conversation limit for this visit. Reuse an existing conversation.");
    else setNotice("");
    go("/"); focusComposer();
  };
  const select = (id) => { chat.selectConversation(id); go("/"); focusComposer(); };
  const prompt = (value) => { chat.setDraft(value); go("/"); focusComposer(); };
  useLayoutEffect(() => {
    if (hidden || settings) return;
    document.title = "AQUA | Your data, clearly";
    document.getElementById("workspace-heading")?.focus({ preventScroll: true });
  }, [hidden, settings]);
  useLayoutEffect(() => {
    const node = dialogRef.current;
    if (drawer && !hidden) node?.showModal(); else node?.close();
  }, [drawer, hidden]);
  useEffect(() => {
    const media = window.matchMedia("(min-width: 901px)");
    const closeOnDesktop = () => { if (media.matches) setDrawer(false); };
    media.addEventListener("change", closeOnDesktop);
    return () => media.removeEventListener("change", closeOnDesktop);
  }, []);
  const navProps = { chat, auth, onNewChat: start, onSelect: select, onPrompt: prompt, onNavigate: go };
  // The rollback changes presentation within this same secured workspace. It
  // must never remount chat state or substitute the pre-P05 auth implementation.
  return <div className={`opal-workspace${sidebar ? "" : " opal-workspace--collapsed"}`} data-ui-shell={UI_SHELL} hidden={hidden} inert={hidden || undefined} style={hidden ? { display: "none" } : undefined}>
    <OpalBackdrop />
    <div className="desktop-sidebar" hidden={!sidebar}><OpalSidebar {...navProps} onClose={() => setSidebar(false)} /></div>
    <dialog ref={dialogRef} className="navigation-dialog" aria-label="Workspace navigation" onCancel={closeDrawer} onClose={() => setDrawer(false)} onClick={(event) => { if (event.target === event.currentTarget) closeDrawer(); }}>
      <OpalSidebar {...navProps} onClose={closeDrawer} />
    </dialog>
    <div className="opal-main"><header className="workspace-header">
      <button type="button" ref={navigationRef} className="icon-button navigation-toggle" aria-label="Open navigation" aria-haspopup="dialog" aria-expanded={drawer}
        onClick={() => { if (window.matchMedia("(max-width: 900px)").matches) setDrawer(true); else setSidebar(true); }}><span aria-hidden="true">☰</span></button>
      <span className="breadcrumb">Workspace <span aria-hidden="true">/</span> <strong title={caption}>{caption}</strong></span>
      <div className="workspace-header__actions"><div className="header-model"><ModelSelector models={chat.models} selectedModelId={chat.selectedModelId} onSelectModel={chat.setModelId} /></div>
        <span className="data-badge">{auth.demoMode ? "Demo data" : auth.canQuery ? "Authorized data" : "Access pending"}</span>
        <button className="icon-button mobile-new-chat" type="button" onClick={start} aria-label="New chat"><ControlIcon asset={plus} /></button>
        <AccountMenu auth={auth} onNavigate={go} /></div>
    </header>
    {notice && <p className="workspace-notice" role="status">{notice}</p>}
    {chat.notice && <p className="workspace-notice" role="alert">{chat.notice}</p>}
    <div className="chat-route" hidden={settings} inert={settings || undefined} style={settings ? { display: "none" } : undefined}>
      <OpalChat chat={chat} auth={auth} inputRef={inputRef} focusRequest={focus} onPrompt={prompt} shell={UI_SHELL} visible={!hidden && !settings} scrollPositions={scrollPositions.current} />
    </div>
    {settings && <SettingsShell auth={auth} onBack={() => go("/")} onNavigate={go} />}
    </div>
  </div>;
}
