import React, { useLayoutEffect } from "react";
import LocalLink from "../components/navigation/LocalLink.jsx";
import { UI_SHELL } from "../services/runtimeConfig.js";
export default function SettingsShell({ auth, onBack, onNavigate }) {
  useLayoutEffect(() => { document.title = "Settings | AQUA"; document.getElementById("settings-heading")?.focus({ preventScroll: true }); }, []);
  return <main className="settings-shell"><p className="breadcrumb">Settings / Your workspace</p>
    <h1 id="settings-heading" tabIndex={-1}>Settings</h1><p>One calm space for your daily work.</p>
    <div className="settings-shell__grid">
      <section><h2>Appearance</h2><p>{UI_SHELL === "legacy" ? "Classic blue theme" : "Opal theme · Pearl accent"}</p><p>Static background specks and a comfortable layout. Your browser’s reduced-motion and contrast preferences are respected.</p><p className="settings-unavailable">Personalization controls aren’t available yet.</p></section>
      <section><h2>Account & access</h2><p>{auth.user?.email || "Fictional demo account"}</p><p>{auth.canQuery ? "Your account can ask questions about the configured data." : "You’re signed in. Ask your AQUA administrator for access to your data."}</p><p>Security limits are managed by your administrator.</p></section>
      <section><h2>Your conversations</h2><p>{auth.demoMode ? "Demo conversations and drafts stay in this visit only." : "Submitted conversations and saved prompts are stored in your account. Unsent drafts stay in this page for this visit; reloading or confirmed sign-out clears drafts."}</p><LocalLink to="/privacy" onNavigate={onNavigate}>Privacy Policy</LocalLink><span aria-hidden="true"> · </span><LocalLink to="/terms" onNavigate={onNavigate}>Terms of Service</LocalLink></section>
    </div><button type="button" className="opal-primary" onClick={onBack}>Back to workspace</button>
  </main>;
}
