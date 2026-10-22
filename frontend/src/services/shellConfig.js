// Deployment selects presentation only. Never infer it from browser storage,
// a URL, a profile, or a server auth capability.
export function selectUiShell(value) {
  return value === "legacy" ? "legacy" : "opal";
}
