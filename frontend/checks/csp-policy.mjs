// Test-only projection of the actual nginx document policies, never app config.
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const BASELINE = Object.freeze({ "object-src": "'none'", "base-uri": "'none'", "frame-ancestors": "'none'" });
const DOCUMENT_POLICY = Object.freeze({
  "default-src": "'none'", ...BASELINE,
  "script-src": "'self' https://accounts.google.com/gsi/client", "script-src-attr": "'none'",
  // Plotly inserts style rules; this exception never authorizes inline scripts.
  "style-src": "'self' 'unsafe-inline' https://accounts.google.com/gsi/style",
  "img-src": "'self' data:", "font-src": "'self'",
  "connect-src": "'self' https://accounts.google.com/gsi/", "frame-src": "https://accounts.google.com/gsi/",
  "form-action": "'self'", "worker-src": "'none'", "media-src": "'none'", "manifest-src": "'self'"
});

function requirePolicy(value, expected) {
  if (typeof value !== "string" || value.length > 4096) throw Error("document_csp_invalid");
  const found = Object.create(null);
  for (const part of value.split(";")) {
    const [name, ...sources] = part.trim().split(/\s+/);
    if (!name || Object.hasOwn(found, name)) throw Error("document_csp_invalid");
    found[name] = sources.join(" ");
  }
  if (Object.keys(found).length !== Object.keys(expected).length
    || Object.entries(expected).some(([name, sources]) => found[name] !== sources)) throw Error("document_csp_invalid");
}

export function readDocumentPolicies(source) {
  if (typeof source !== "string" || source.length > 32768) throw Error("document_csp_invalid");
  const headers = [...source.matchAll(/^\s*add_header (Content-Security-Policy(?:-Report-Only)?) "([^"\r\n]+)" always;$/gm)];
  const select = name => headers.filter(match => match[1] === name).map(match => match[2]);
  const enforced = select("Content-Security-Policy"), reportOnly = select("Content-Security-Policy-Report-Only");
  if (enforced.length !== 2 || reportOnly.length !== 0 || enforced[0] !== enforced[1]) throw Error("document_csp_invalid");
  requirePolicy(enforced[0], DOCUMENT_POLICY);
  const permissions = source.match(/^\s*set \$aqua_permissions_policy "([a-z0-9-]+=\(\)(?:, [a-z0-9-]+=\(\))*)";$/m);
  if (!permissions) throw Error("document_permissions_policy_invalid");
  return Object.freeze({ enforced: enforced[0], permissions: permissions[1],
    sha256: createHash("sha256").update(JSON.stringify([enforced[0]])).digest("hex") });
}

export function loadDocumentPolicies() {
  return readDocumentPolicies(readFileSync(new URL("../nginx.conf", import.meta.url), "utf8"));
}

export function documentPolicyHeaders(mode = "source", policies = loadDocumentPolicies()) {
  if (!["source", "enforced-fixture"].includes(mode)) throw Error("document_csp_mode_invalid");
  // Revalidate at this pure boundary so fixture callers cannot inject a policy.
  requirePolicy(policies.enforced, DOCUMENT_POLICY);
  return [{ name: "Content-Security-Policy", value: policies.enforced }];
}
