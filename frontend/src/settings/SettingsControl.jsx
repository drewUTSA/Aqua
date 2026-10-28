import React from "react";
import { ACCOUNT_RULES, DEVICE_RULES } from "./schema.js";
import { usePreferences } from "./PreferencesProvider.jsx";
import { valueLabel } from "./controls.js";

function OrderedSections({ value, id, disabled, onChange }) {
  const titles = { projects: "Projects", recents: "Recents" };
  // Version-1 imports may retain the former prompts section. Keep that data
  // readable, but expose only the two navigation sections used by this UI.
  const sections = value.filter((section) => Object.hasOwn(titles, section));
  return <fieldset id={id} disabled={disabled} className="settings-section-order" aria-labelledby={`${id}-label`}><legend className="visually-hidden">Optional sidebar sections</legend>
    {Object.entries(titles).map(([section, title]) => <label key={section}><input type="checkbox" checked={sections.includes(section)}
      onChange={(event) => onChange(event.target.checked ? [...sections, section] : sections.filter((item) => item !== section))} />{title}</label>)}
    <ol>{sections.map((section, index) => <li key={section}><span>{titles[section]}</span>
      <button type="button" disabled={disabled || index === 0} aria-label={`Move ${titles[section]} up`} onClick={() => {
        const next = [...sections]; [next[index - 1], next[index]] = [next[index], next[index - 1]]; onChange(next);
      }}>↑</button><button type="button" disabled={disabled || index === sections.length - 1} aria-label={`Move ${titles[section]} down`} onClick={() => {
        const next = [...sections]; [next[index], next[index + 1]] = [next[index + 1], next[index]]; onChange(next);
      }}>↓</button></li>)}</ol>
  </fieldset>;
}
export default function SettingsControl({ field, suffix = "" }) {
  const preferences = usePreferences(), { scope, key, label, help } = field;
  const rule = (scope === "account" ? ACCOUNT_RULES : DEVICE_RULES)[key], value = preferences.draft[scope][key];
  const id = `settings-field-${key}${suffix}`, helper = `${id}-help`;
  const disabled = preferences.saving || scope === "account" && (!preferences.ready || preferences.loading)
    || scope === "device" && preferences.deviceWritable === false;
  const change = (next) => preferences.change(scope, key, next);
  return <div className="settings-control" data-preference-scope={scope}>
    <div>{rule.kind === "order" ? <span id={`${id}-label`} className="settings-control-label">{label}</span> : <label htmlFor={id}>{label}</label>}<span className="settings-scope">{scope === "account" ? "Account" : "This device"}</span>
      {help && <p id={helper}>{help}</p>}</div>
    {rule.kind === "boolean" ? <label className="settings-toggle"><input id={id} type="checkbox" checked={value}
      disabled={disabled} aria-describedby={help ? helper : undefined} onChange={(event) => change(event.target.checked)} />
      <span>{value ? "On" : "Off"}</span></label>
      : rule.kind === "order" ? <OrderedSections id={id} value={value} disabled={disabled} onChange={change} />
        : rule.kind === "integer" ? <div className="settings-range"><input id={id} type="range" min={rule.min} max={rule.max} step="1"
          value={value} disabled={disabled} aria-describedby={help ? helper : undefined} onChange={(event) => change(Number(event.target.value))} />
          <output htmlFor={id}>{value}% conversation</output></div>
          : <select id={id} value={value} disabled={disabled} aria-describedby={help ? helper : undefined}
            onChange={(event) => change(typeof rule.default === "number" ? Number(event.target.value) : event.target.value)}>
            {rule.values.map((option) => <option key={option} value={option}>{valueLabel(key, option)}</option>)}
          </select>}
  </div>;
}
