import { DEVICE_DEFAULTS, clone, isRecord, validateValues } from "./schema.js";

const storageKey = (owner) => `aqua-preferences-device:v1:${owner}`;
function browserStorage() { return globalThis.localStorage; }
export function readDevicePreferences(owner, storage) {
  try {
    const store = storage ?? browserStorage(), text = store?.getItem(storageKey(owner));
    if (!text) return { values: clone(DEVICE_DEFAULTS), warning: "", writable: true };
    if (text.length > 65536) throw new Error("oversized");
    const value = JSON.parse(text);
    if (isRecord(value) && value.schemaVersion !== 1) return { values: clone(DEVICE_DEFAULTS), writable: false,
      warning: "This device has preferences from a newer AQUA version. They are preserved; device saving is unavailable." };
    if (!isRecord(value) || Object.keys(value).some((key) => !["schemaVersion", "values"].includes(key))) {
      return { values: clone(DEVICE_DEFAULTS), writable: false, warning: "Unrecognized device preferences are preserved. Device saving is unavailable until they can be read safely." };
    }
    try { return { values: { ...clone(DEVICE_DEFAULTS), ...validateValues(value.values, "device", { partial: true }) }, warning: "", writable: true }; }
    catch { return { values: clone(DEVICE_DEFAULTS), writable: false, warning: "Unsupported saved device choices are preserved. Device saving is unavailable in this version." }; }
  } catch { return { values: clone(DEVICE_DEFAULTS), writable: true,
    warning: "Device preferences could not be read. Safe defaults are shown; local saving may be unavailable." }; }
}
export function saveDevicePreferences(owner, values, storage) {
  const confirmed = validateValues(values, "device"), store = storage ?? browserStorage();
  if (!store) throw new Error("Device storage is unavailable.");
  const current = readDevicePreferences(owner, store);
  if (!current.writable) throw new Error(current.warning);
  const text = JSON.stringify({ schemaVersion: 1, values: confirmed });
  store.setItem(storageKey(owner), text);
  // A storage shim may reject writes without throwing. Confirm the stated scope.
  if (store.getItem(storageKey(owner)) !== text) throw new Error("Device storage did not confirm the change.");
  return confirmed;
}
export function purgeDevicePreferences(owner, storage) {
  if (!owner) return;
  try { (storage ?? browserStorage())?.removeItem(storageKey(owner)); } catch { /* Best effort; values contain no private content. */ }
}
