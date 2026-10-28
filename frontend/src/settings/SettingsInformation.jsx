import React from "react";
import LocalLink from "../components/navigation/LocalLink.jsx";
import { usePreferences } from "./PreferencesProvider.jsx";
import AccountFoundation from "./AccountFoundation.jsx";

export default function SettingsInformation({ category, auth, onNavigate }) {
  const { draft } = usePreferences();
  if (category === "chat") return <aside className="settings-information"><p>Choose an available model beside the composer for the next question.</p>
    <p>Response style, personal instructions and response-language preferences are unavailable until their server capabilities are implemented.</p>
    <p>Analysis currently reports bounded progress and a completed response; there is no partial-response streaming switch.</p></aside>;
  if (category === "workspace") return <aside className="settings-information"><p>New Chat remains the start screen. Optional attachment tools are unavailable; the composer and send/stop controls remain visible.</p></aside>;
  if (category === "accessibility") return <aside className="settings-information"><h3>Keyboard shortcuts</h3>
    <p>Tab and Shift+Tab move between controls. Escape closes menus and dialogs. Shift+Enter adds a new line. The Send shortcut is available in Chat & AI.</p>
    <p>Optional single-key shortcuts are not installed. Browser and assistive technology shortcuts remain available.</p></aside>;
  if (category === "notifications") return <aside className="settings-information"><p>In-app analysis status, errors, session expiry and save feedback remain available.</p>
    <p>Browser notifications, optional email subscriptions, sounds, preview settings and quiet hours are unavailable in this release. No preference import or reset requests permission or subscribes you.</p>
    <button type="button" disabled>Notification subscriptions unavailable</button></aside>;
  if (category === "account") return <AccountFoundation auth={auth} />;
  if (category === "region") {
    const zone = draft.account.timezone === "device" ? Intl.DateTimeFormat().resolvedOptions().timeZone : draft.account.timezone;
    const options = { dateStyle: draft.account.date_style, timeStyle: "short", timeZone: zone,
      ...(draft.account.time_format === "locale" ? {} : { hour12: draft.account.time_format === "12" }) };
    return <aside className="settings-information"><h3>Formatting preview</h3><p>{new Intl.DateTimeFormat(draft.account.locale, options).format(new Date("2026-10-28T18:30:00Z"))} · {zone}</p>
      <p>{new Intl.NumberFormat(draft.account.locale).format(12345.6789)} · USD {new Intl.NumberFormat(draft.account.locale, { minimumFractionDigits: 2 }).format(1234.5)}</p>
      <p>Source currency and timestamps remain unchanged. The interface is English; no unimplemented language packs or currency conversions are offered.</p></aside>;
  }
  if (category === "privacy") return <aside className="settings-information"><p>Preference files exclude identity, email, sessions, credentials, personal instructions, chats, chart data, permissions and consent.</p>
    <p>Private data export, history deletion and account deletion require the separate privacy operations release. A preference reset does not delete data or revoke sessions.</p>
    <button type="button" disabled>Private data operations unavailable</button><p>
      <LocalLink to="/privacy" onNavigate={onNavigate}>Privacy Policy</LocalLink><span aria-hidden="true"> · </span>
      <LocalLink to="/terms" onNavigate={onNavigate}>Terms of Service</LocalLink></p></aside>;
  return null;
}
