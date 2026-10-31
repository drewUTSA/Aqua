import React, { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useChat } from "../../hooks/useChat.js";
import { useWorkspace } from "../../hooks/useWorkspace.js";
import OpalSidebar from "./OpalSidebar.jsx";
import VisualWorkspace from "./VisualWorkspace.jsx";
import OpalBackdrop from "../auth/OpalBackdrop.jsx";
import { UI_SHELL } from "../../services/runtimeConfig.js";
import { usePreferences } from "../../settings/PreferencesProvider.jsx";
import { useNotifications } from "../../settings/NotificationProvider.jsx";
import "../../styles/workspace.css";
import "../../styles/legacy-workspace.css";
import "../../styles/workspace-library.css";
import "../../styles/preferences.css";
import "../../styles/homepage.css";

const SettingsShell = lazy(() => import("../../pages/SettingsShell.jsx"));
const PromptLibraryDialog = lazy(() => import("./PromptLibraryDialog.jsx"));

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
  const notifications=useNotifications();
  const chat = useWorkspace({ canQuery: auth.canQuery, canReadResults: auth.session?.can_query === true,
    csrfToken: auth.csrfToken, onAuthFailure: auth.refresh, suspended: hidden, onLiveCompletion:event=>notifications.observe({...event,alreadyVisible:event.alreadyVisible&&props.path==="/"&&!hidden}) });
  return <WorkspaceView {...props} chat={chat} />;
}
function WorkspaceView({ auth, hidden, path, onNavigate, chat }) {
  const preferences = usePreferences();
  const { account, device } = preferences.effective;
  const [systemDark, setSystemDark] = useState(() => typeof window === "undefined" || window.matchMedia("(prefers-color-scheme: dark)").matches);
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const update = () => setSystemDark(media.matches);
    media.addEventListener("change", update); return () => media.removeEventListener("change", update);
  }, []);
  const theme = account.theme === "system" ? systemDark ? "opal" : "light" : account.theme;
  const [sidebar, setSidebar] = useState(true), [drawer, setDrawer] = useState(false), [focus, setFocus] = useState(0);
  useEffect(() => { setSidebar(device.sidebar !== "collapsed"); }, [device.sidebar]);
  const [notice, setNotice] = useState(""), [promptsOpen, setPromptsOpen] = useState(false);
  const inputRef = useRef(null), dialogRef = useRef(null), navigationRef = useRef(null);
  const scrollPositions = useRef(new Map());
  const settings = path === "/settings";
  const caption = settings ? "Settings" : chat.durable && chat.active?.revision ? chat.active.title : "New chat";
  const focusComposer = useCallback(() => setFocus((value) => value + 1), []);
  const closeDrawer = () => { dialogRef.current?.close(); setDrawer(false); navigationRef.current?.focus(); };
  const go = (target) => { closeDrawer(); onNavigate(target); };
  const start = (projectId = null) => void preferences.requestLeave(() => {
    if (!chat.startConversation({ projectId })) setNotice("You have reached the conversation limit for this visit. Reuse an existing conversation.");
    else setNotice("");
    go("/"); focusComposer();
  });
  const select = (id, summary) => void preferences.requestLeave(() => { chat.selectConversation(id, summary); go("/"); focusComposer(); });
  const prompt = (value) => void preferences.requestLeave(() => { chat.setDraft(value); go("/"); focusComposer(); });
  const openPrompts = () => { chat.openPrompts?.(); setPromptsOpen(true); };
  useEffect(() => { if (hidden || settings) setPromptsOpen(false); }, [hidden, settings]);
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
  const showNewChat = chat.messages.length > 0 || Boolean(chat.active?.messageCount || chat.pending || chat.uncertain);
  const navProps = { chat, auth, preferences: account, showNewChat, onNewChat: start, onSelect: select, onNavigate: go };
  // The rollback changes presentation within this same secured workspace. It
  // must never remount chat state or substitute the pre-P05 auth implementation.
  return <div className={`opal-workspace${sidebar ? "" : " opal-workspace--collapsed"}`} data-ui-shell={UI_SHELL} data-theme={theme}
    data-accent={account.accent} data-density={account.density} data-surface={account.surface} data-font={account.font}
    data-contrast={device.contrast} data-spacing={device.line_spacing} data-width={device.conversation_width}
    data-motion={device.motion} data-wrap-code={account.wrap_code} hidden={hidden} inert={hidden || undefined}
    style={{ "--pref-text-scale": device.text_scale / 100, ...(hidden ? { display: "none" } : {}) }}>
    {account.specks !== "off" && <OpalBackdrop />}
    <div className="desktop-sidebar" hidden={!sidebar}><OpalSidebar {...navProps} onClose={() => { setSidebar(false); preferences.persistDeviceValue("sidebar", "collapsed"); }} /></div>
    <dialog ref={dialogRef} className="navigation-dialog" aria-label="Workspace navigation" onCancel={closeDrawer} onClose={() => setDrawer(false)} onClick={(event) => { if (event.target === event.currentTarget) closeDrawer(); }}>
      <OpalSidebar {...navProps} onClose={closeDrawer} />
    </dialog>
    <div className="opal-main"><header className="workspace-header">
      <button type="button" ref={navigationRef} className="icon-button navigation-toggle" aria-label="Open navigation" aria-haspopup="dialog" aria-expanded={drawer}
        onClick={() => { if (window.matchMedia("(max-width: 900px)").matches) setDrawer(true); else { setSidebar(true); preferences.persistDeviceValue("sidebar", "expanded"); } }}><span aria-hidden="true">☰</span></button>
      <span className="breadcrumb"><strong title={caption}>{caption}</strong></span>
      {(auth.demoMode || !auth.canQuery) && <span className="data-badge">{auth.demoMode ? "Demo data" : "Access pending"}</span>}
    </header>
    {notice && <p className="workspace-notice" role="status">{notice}</p>}
    {chat.notice && <p className="workspace-notice" role="alert">{chat.notice}</p>}
    {!settings && preferences.error && <p className="workspace-notice" role="alert">{preferences.error} Open Settings to review or retry.</p>}
    <div className="chat-route" hidden={settings} inert={settings || undefined} style={settings ? { display: "none" } : undefined}>
      <VisualWorkspace chat={chat} auth={auth} preferences={{ account, device }} onDeviceChange={preferences.persistDeviceValue} chartTheme={theme} inputRef={inputRef} focusRequest={focus} onOpenPrompts={openPrompts} shell={UI_SHELL} visible={!hidden && !settings} scrollPositions={scrollPositions.current} />
    </div>
    {settings && <Suspense fallback={<p role="status">Opening Settings…</p>}><SettingsShell auth={auth} onBack={() => go("/")} onNavigate={go} /></Suspense>}
    {promptsOpen && !hidden && !settings && <Suspense fallback={<p role="status">Opening saved prompts…</p>}><PromptLibraryDialog chat={chat} suggestions={account.suggestions} onClose={() => setPromptsOpen(false)} onPrompt={(value) => { prompt(value); setPromptsOpen(false); }} /></Suspense>}
    </div>
  </div>;
}
