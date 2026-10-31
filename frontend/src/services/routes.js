// Email bearers live only in page memory. Never accept a caller's redirect.
export const AUTH_PATHS = new Set(["/signin", "/register", "/forgot-password", "/check-email", "/registration-sent", "/verify-email", "/reset-password"]);
export const ACCOUNT_ACTION_PATHS = new Set(["/account-action/password_add", "/account-action/email_change_new", "/account-action/email_change_old"]);
export const LOCAL_PATHS = new Set(["/", "/settings", "/privacy", "/terms", ...AUTH_PATHS, ...ACCOUNT_ACTION_PATHS]);
const PROOF_PATHS = new Set(["/verify-email", "/reset-password"]);
export function consumeLocation(location, history) {
  // A pathname beginning // or containing a backslash can be interpreted as a
  // network-path reference by History. Normalize it to our own 404 route.
  const path = /^\/(?!\/)/.test(location.pathname) && !location.pathname.includes("\\") ? location.pathname : "/not-found";
  const fragment = location.hash || "";
  const match = PROOF_PATHS.has(path) && /^#token=([A-Za-z0-9_-]{43})$/.exec(fragment);
  if (fragment || location.search) history.replaceState(null, "", path);
  return { path, proof: match ? match[1] : null };
}
export function navigateLocal(path, history, update) {
  if (!LOCAL_PATHS.has(path)) return false;
  history.pushState(null, "", path);
  update({ path, proof: null });
  return true;
}
