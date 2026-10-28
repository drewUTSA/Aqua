import React, { useRef, useState } from "react";
import { usePreferences } from "./PreferencesProvider.jsx";
import PreferenceDialog from "./PreferenceDialog.jsx";
import { CATEGORIES, valueLabel } from "./controls.js";
import { equal, exportPreferences, MAX_PREFERENCE_BYTES, parseImport } from "./schema.js";

const title = (scope, key) => CATEGORIES.flatMap((category) => category.fields).find((field) => field.scope === scope && field.key === key)?.label || key;
const display = (key, value) => Array.isArray(value) ? value.join(", ") || "None" : typeof value === "boolean" ? value ? "On" : "Off" : valueLabel(key, value);
export function DraftComparison({ before, after, imported = false }) {
  return <div className="settings-comparison">{["account", "device"].map((scope) => {
    const entries = Object.entries(after[scope] || {}).filter(([key, value]) => !equal(value, before[scope][key]));
    if (!entries.length) return null;
    return <section key={scope}><h3>{scope === "account" ? "Account" : "This device"}</h3><dl>{entries.map(([key, value]) => <div key={key}>
      <dt>{title(scope, key)}</dt><dd>{display(key, before[scope][key])}<span aria-hidden="true"> → </span><span className="visually-hidden"> changes to </span>{display(key, value)}</dd>
    </div>)}</dl></section>;
  })}{imported && <p>Omitted fields keep their current draft values. Imported device values remain scoped to this device.</p>}</div>;
}
export default function PreferenceTransfers() {
  const preferences = usePreferences();
  const [includeDevice, setIncludeDevice] = useState(false), [proposal, setProposal] = useState(null), [error, setError] = useState("");
  const ticket = useRef(0), input = useRef(null);
  const close = () => { ticket.current++; setProposal(null); if (input.current) input.current.value = ""; };
  const choose = async (event) => {
    const file = event.target.files?.[0], attempt = ++ticket.current;
    setProposal(null); setError(""); if (!file) return;
    try {
      if (file.size > MAX_PREFERENCE_BYTES) throw new Error("Preference files must be 64 KiB or smaller.");
      const parsed = parseImport(await file.text());
      if (attempt === ticket.current) setProposal(parsed);
    } catch (failure) {
      if (attempt === ticket.current) {
        setProposal(null); setError(failure.message || "This preference file is not supported.");
        if (input.current) input.current.value = "";
      }
    }
  };
  const download = () => {
    setError("");
    try {
      const text = exportPreferences(preferences.saved.account, includeDevice ? preferences.saved.device : undefined);
      const blob = new Blob([text], { type: "application/json" }), url = URL.createObjectURL(blob), link = document.createElement("a");
      link.href = url; link.download = "aqua-preferences-v1.json"; link.click(); setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch { setError("Preferences could not be exported. Your saved values and draft are unchanged."); }
  };
  return <section className="settings-transfers" aria-labelledby="preference-transfer-heading"><h3 id="preference-transfer-heading">Preference files</h3>
    <p>Export last confirmed saved preferences. Unsaved draft values are excluded. Imports are JSON, up to 64 KiB, and require a review before changing your draft.</p>
    <label><input type="checkbox" checked={includeDevice} onChange={(event) => setIncludeDevice(event.target.checked)} /> Include this device’s saved preferences in export</label>
    <div className="settings-actions"><button type="button" onClick={download} disabled={!preferences.ready || preferences.saving}>Export preferences</button>
      <label className="settings-file-label" htmlFor="settings-import-file">Import preferences<input id="settings-import-file" ref={input} type="file" accept=".json,application/json"
        disabled={preferences.saving || !preferences.ready || preferences.needsReload} onChange={choose} /></label></div>
    {error && <div className="settings-import-error"><p role="alert" className="settings-error">{error} Your existing draft and preview are unchanged.</p>
      <button type="button" onClick={() => input.current?.click()}>Choose another file</button><button type="button" onClick={() => { close(); setError(""); }}>Cancel import</button></div>}
    {proposal && <PreferenceDialog title="Review preference import" onClose={close}>
      <p>This changes the draft only. Save changes is required before account or device preferences are saved.</p>
      <DraftComparison before={preferences.draft} after={proposal} imported />
      <div className="settings-dialog-actions"><button type="button" autoFocus onClick={close}>Cancel import</button>
        <button type="button" disabled={preferences.saving || !preferences.ready || preferences.needsReload || Boolean(proposal.device) && preferences.deviceWritable === false} onClick={() => {
          preferences.applyDraft(proposal, "Preference import"); close();
        }}>Apply to draft</button></div>
    </PreferenceDialog>}
  </section>;
}
