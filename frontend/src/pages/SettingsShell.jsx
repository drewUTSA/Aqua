import React, { useEffect, useLayoutEffect, useState } from "react";
import { usePreferences } from "../settings/PreferencesProvider.jsx";
import { ACCOUNT_DEFAULTS, DEVICE_DEFAULTS } from "../settings/schema.js";
import { CATEGORIES, sectionDefaults } from "../settings/controls.js";
import SettingsControl from "../settings/SettingsControl.jsx";
import SettingsInformation from "../settings/SettingsInformation.jsx";
import PreferenceDialog from "../settings/PreferenceDialog.jsx";
import PreferenceTransfers, { DraftComparison } from "../settings/PreferenceTransfers.jsx";
import "../styles/settings.css";

function AppearancePreview() {
  return <aside className="settings-preview" aria-label="Synthetic appearance preview"><p className="settings-scope">Live presentation preview · synthetic data</p>
    <nav aria-label="Preview navigation"><span>Overview</span><span>Example project</span></nav><h3>A clearer view of your data</h3>
    <p className="settings-preview-message">Example answer: revenue increased over three months.</p>
    <div className="settings-preview-chart" role="img" aria-label="Example revenue: January 20, February 30, March 40. Synthetic data.">
      <span><i />Jan · 20</span><span><i />Feb · 30</span><span><i />Mar · 40</span></div>
    <label htmlFor="settings-preview-composer">Example composer</label><textarea id="settings-preview-composer" readOnly value="Ask about your data…" rows={1} />
    <button type="button">Example button and focus ring</button>
  </aside>;
}
export default function SettingsShell({ auth, onBack, onNavigate }) {
  const preferences = usePreferences(), [categoryId, setCategory] = useState("appearance"), [search, setSearch] = useState("");
  const [mobileIndex, setMobileIndex] = useState(true), [reset, setReset] = useState(null);
  const category = CATEGORIES.find((item) => item.id === categoryId), query = search.trim().toLowerCase();
  const results = query ? CATEGORIES.map((item) => ({ ...item, fields: item.fields.filter((field) => `${item.title} ${field.label} ${field.help}`.toLowerCase().includes(query)) }))
    .filter((item) => item.fields.length || `${item.title} ${item.description}`.toLowerCase().includes(query)) : [category];
  useLayoutEffect(() => { document.title = "Settings | AQUA"; document.getElementById("settings-heading")?.focus({ preventScroll: true }); }, []);
  useEffect(() => { document.title = query ? "Search settings | AQUA" : `${category.title} settings | AQUA`; }, [category.title, query]);
  const navigate = (target) => preferences.requestLeave(() => onNavigate(target));
  return <main className="settings-shell settings-page" data-mobile-index={mobileIndex && !query ? "true" : "false"}>
    <div className="settings-heading-row"><div><p className="breadcrumb">Settings / {category.title}</p><h1 id="settings-heading" tabIndex={-1}>Settings</h1>
      <p>One calm space for your daily work. Preview changes, then choose where to save them.</p><p className="settings-scope">{auth.user?.email || "Demo account"}</p></div>
      <button type="button" onClick={() => preferences.requestLeave(onBack)}>Back to workspace</button></div>
    {auth.demoMode && <p className="settings-information" role="status">Demo preferences apply to this visit only. They are not saved to an account or this device.</p>}
    {preferences.loading && <p role="status">Loading account preferences… Device preferences remain available.</p>}
    {preferences.deviceWarning && <p className="settings-warning" role="status">{preferences.deviceWarning}</p>}
    {(preferences.error || preferences.needsReload || preferences.conflict) && <div className="settings-error" role="alert"><p>{preferences.error || "Reload account preferences before saving account changes."}</p>
      <p>Your unsaved draft remains available. Reload account values to discard its account changes, or load the latest revision and review your retained draft.</p>
      <div className="settings-actions"><button type="button" disabled={preferences.loading || preferences.saving} onClick={() => preferences.reload()}>Reload account values</button>
        <button type="button" disabled={preferences.loading || preferences.saving} onClick={() => preferences.reload({ reapply: true })}>Review and reapply draft</button></div></div>}
    <label className="settings-search" htmlFor="settings-search">Search settings<input id="settings-search" type="search" maxLength={100} value={search}
      autoComplete="off" placeholder="Search labels and categories" onChange={(event) => setSearch(event.target.value)} /></label>
    <div className="settings-layout"><nav className="settings-categories" aria-label="Settings categories">{CATEGORIES.map((item) => <button type="button" key={item.id}
      data-settings-category={item.id} aria-current={!query && item.id === categoryId ? "page" : undefined} onClick={() => {
        setCategory(item.id); setSearch(""); setMobileIndex(false);
        requestAnimationFrame(() => document.getElementById("settings-section-heading")?.focus({ preventScroll: true }));
      }}>{item.title}</button>)}</nav>
      <div className="settings-content"><button className="settings-category-back" type="button" onClick={() => {
        setMobileIndex(true); requestAnimationFrame(() => document.querySelector(`[data-settings-category="${categoryId}"]`)?.focus());
      }}>All settings categories</button>
        {query && <><h2 id="settings-section-heading" tabIndex={-1}>Search results</h2><p role="status">{results.length} matching {results.length === 1 ? "category" : "categories"}</p></>}
        {query && !results.length && <p role="status">No settings match. Try another word.</p>}
        {results.map((item) => <section key={item.id} className="settings-category-section" aria-labelledby={!query ? "settings-section-heading" : `settings-section-${item.id}`}>
          <h2 id={!query ? "settings-section-heading" : `settings-section-${item.id}`} tabIndex={-1}>{item.title}</h2><p>{item.description}</p>
          {item.fields.map((field) => <SettingsControl key={`${field.scope}-${field.key}`} field={field} suffix={query ? `-${item.id}` : ""} />)}
          <SettingsInformation category={item.id} auth={auth} onNavigate={navigate} />
          {item.id === "appearance" && !query && <AppearancePreview />}
          {item.id === "privacy" && <PreferenceTransfers />}
        </section>)}
        {!query && category.fields.length > 0 && <button type="button" disabled={preferences.saving} onClick={() => setReset("section")}>Reset this section</button>}
        <details className="settings-draft-review"><summary>Review draft against saved preferences</summary><DraftComparison before={preferences.saved} after={preferences.draft} /></details>
      </div>
    </div>
    <footer className="settings-savebar"><div><span aria-live="polite">{preferences.saving ? "Saving preferences…" : preferences.dirty ? "Unsaved preference changes" : "No unsaved preference changes"}</span>
      {preferences.status && <p role="status">{preferences.status}</p>}{preferences.undo && <button type="button" disabled={preferences.saving} onClick={preferences.undoDraft}>Undo {preferences.undo.label.toLowerCase()}</button>}</div>
      <div className="settings-actions"><button type="button" disabled={preferences.saving} onClick={() => setReset("all")}>Reset all preferences</button>
        <button type="button" disabled={!preferences.dirty || preferences.saving} onClick={preferences.cancel}>Cancel changes</button>
        <button type="button" className="opal-primary" disabled={!preferences.dirty || preferences.saving || preferences.loading} onClick={preferences.save}>Save changes</button></div></footer>
    {reset && <PreferenceDialog title={reset === "all" ? "Reset all preferences?" : `Reset ${category.title.toLowerCase()} preferences?`} onClose={() => setReset(null)}>
      <p>This restores {reset === "all" ? "account and device preference" : "this section’s preference"} defaults in the draft. Save changes is required to keep them. Chats, accounts, permissions, consent and sessions are unaffected.</p>
      {reset === "all" && <p>Included categories: Appearance, Workspace, Chat & AI, Charts & tables, Accessibility, and Language & region. Account security, notifications, and private data operations are unchanged.</p>}
      <DraftComparison before={preferences.draft} after={reset === "all" ? { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS }
        : sectionDefaults(category, ACCOUNT_DEFAULTS, DEVICE_DEFAULTS)} />
      <p>Cancel changes later restores the last saved preferences. Undo reset restores the current unsaved draft.</p>
      <div className="settings-dialog-actions"><button type="button" autoFocus onClick={() => setReset(null)}>Keep editing</button>
        <button type="button" onClick={() => {
          preferences.applyDraft(reset === "all" ? { account: ACCOUNT_DEFAULTS, device: DEVICE_DEFAULTS }
            : sectionDefaults(category, ACCOUNT_DEFAULTS, DEVICE_DEFAULTS), "Reset"); setReset(null);
        }}>Reset draft</button></div></PreferenceDialog>}
  </main>;
}
