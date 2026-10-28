// Closed P10a account snapshots. Future capabilities require a reviewed contract.
const CAPABILITIES = Object.freeze({
  profile_edit: true, method_list: true, session_list: true, recent_proof: false,
  email_change: false, password_change: false, google_link: false, google_unlink: false,
  session_revoke: false, sessions_revoke_all: false, notification_delivery: false,
});
const FORBIDDEN_TEXT = /[\p{C}\p{Zl}\p{Zp}]/u;
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const encoder = new TextEncoder();
const requireValue = (condition) => { if (!condition) throw new Error("account_invalid"); };
const plainRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value)
  && [Object.prototype, null].includes(Object.getPrototypeOf(value));

function exactKeys(value, keys) {
  requireValue(plainRecord(value));
  const actual = Reflect.ownKeys(value);
  requireValue(actual.length === keys.length && actual.every((key) => typeof key === "string" && keys.includes(key)
    && Object.hasOwn(Object.getOwnPropertyDescriptor(value, key), "value")));
}

function plainText(value, maximum, empty = false) {
  requireValue(typeof value === "string" && !FORBIDDEN_TEXT.test(value));
  const length = [...value].length;
  requireValue(length >= (empty ? 0 : 1) && length <= maximum);
  return value;
}

function boundedList(value, minimum, maximum) {
  requireValue(Array.isArray(value) && value.length >= minimum && value.length <= maximum);
  const keys = Reflect.ownKeys(value);
  requireValue(keys.length === value.length + 1 && keys.every((key) => key === "length"
    || typeof key === "string" && /^(0|[1-9]\d*)$/.test(key) && Number(key) < value.length
      && Object.hasOwn(Object.getOwnPropertyDescriptor(value, key), "value")));
  return value;
}

export function accountOwner(value) {
  requireValue(typeof value === "string" && UUID.test(value));
  return value;
}

export function accountRevision(value) {
  requireValue(Number.isSafeInteger(value) && value >= 1);
  return value;
}

export function normalizedDisplayName(value) {
  // Validate before trimming so newlines, format controls and surrogates cannot disappear.
  requireValue(typeof value === "string" && !FORBIDDEN_TEXT.test(value));
  const normalized = value.normalize("NFC").trim();
  plainText(normalized, 120);
  requireValue(encoder.encode(normalized).byteLength <= 512);
  return normalized;
}

function capabilities(value) {
  exactKeys(value, Object.keys(CAPABILITIES));
  requireValue(Object.entries(CAPABILITIES).every(([key, enabled]) => value[key] === enabled));
  return { ...CAPABILITIES };
}

function picture(value) {
  requireValue(typeof value === "string" && value.length <= 1024 && !FORBIDDEN_TEXT.test(value));
  if (value === "") return value;
  const url = new URL(value);
  requireValue(url.protocol === "https:" && !url.username && !url.password
    && (url.hostname === "googleusercontent.com" || url.hostname.endsWith(".googleusercontent.com")));
  return value;
}

function email(value) {
  plainText(value, 320);
  requireValue(!/[\s\x7f]/u.test(value) && value.split("@").length === 2 && value.split("@").every(Boolean));
  return value;
}

// Parse a bounded ISO instant without Date.parse's invalid-date rollover. Keep
// microseconds for ordering: PostgreSQL can emit distinct instants within 1 ms.
function instant(value) {
  requireValue(typeof value === "string" && value.length <= 40);
  const parts = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?(Z|[+-](\d{2}):(\d{2}))$/.exec(value);
  requireValue(parts && Number(parts[1].slice(0, 4)) >= 1);
  if (parts[3] !== "Z") {
    const hours = Number(parts[4]), minutes = Number(parts[5]);
    requireValue(hours <= 14 && minutes <= 59 && (hours < 14 || minutes === 0));
  }
  const calendar = new Date(`${parts[1]}Z`);
  requireValue(Number.isFinite(calendar.getTime()) && calendar.toISOString().slice(0, 19) === parts[1]);
  const milliseconds = Date.parse(parts[1] + parts[3]);
  requireValue(Number.isSafeInteger(milliseconds));
  return BigInt(milliseconds) * 1000n + BigInt((parts[2] || "").padEnd(6, "0"));
}

export function accountProfile(value, expectedOwner) {
  accountOwner(expectedOwner);
  exactKeys(value, ["schemaVersion", "revision", "user", "email_verified", "capabilities"]);
  requireValue(value.schemaVersion === 1 && value.email_verified === true);
  exactKeys(value.user, ["id", "name", "picture", "email"]);
  requireValue(accountOwner(value.user.id) === expectedOwner);
  // Google-created legacy profiles may have an empty or non-NFC name. Editing
  // uses the stricter new-name policy; reading does not silently rewrite it.
  plainText(value.user.name, 120, true);
  requireValue(encoder.encode(value.user.name).byteLength <= 512);
  return {
    schemaVersion: 1, revision: accountRevision(value.revision),
    user: { id: expectedOwner, name: value.user.name, picture: picture(value.user.picture), email: email(value.user.email) },
    email_verified: true, capabilities: capabilities(value.capabilities),
  };
}

export function accountMethods(value) {
  exactKeys(value, ["schemaVersion", "password", "google", "capabilities"]);
  requireValue(value.schemaVersion === 1);
  exactKeys(value.password, ["linked", "available", "changed_at"]);
  exactKeys(value.google, ["linked", "available", "identities"]);
  const password = value.password, google = value.google;
  requireValue(typeof password.linked === "boolean" && typeof password.available === "boolean"
    && (!password.available || password.linked) && (password.linked ? password.changed_at !== null : password.changed_at === null));
  if (password.linked) instant(password.changed_at);
  requireValue(typeof google.linked === "boolean" && typeof google.available === "boolean"
    && (!google.available || google.linked));
  boundedList(google.identities, 0, 20);
  requireValue(google.linked === (google.identities.length > 0));
  const identifiers = new Set();
  const identities = google.identities.map((identity) => {
    exactKeys(identity, ["id", "linked_at"]);
    const id = accountOwner(identity.id);
    requireValue(!identifiers.has(id)); identifiers.add(id); instant(identity.linked_at);
    return { id, linked_at: identity.linked_at };
  });
  return {
    schemaVersion: 1,
    password: { linked: password.linked, available: password.available, changed_at: password.changed_at },
    google: { linked: google.linked, available: google.available, identities },
    capabilities: capabilities(value.capabilities),
  };
}

function deviceLabel(value) {
  plainText(value, 120);
  requireValue(value === value.trim());
  // Labels are stored text, not verified browser or location evidence. Only
  // these generic presentation labels may enter the account interface.
  return ["Desktop browser", "Mobile browser", "Unknown device"].includes(value) ? value : "Unknown device";
}

export function accountSessions(value) {
  exactKeys(value, ["schemaVersion", "items", "capabilities"]);
  requireValue(value.schemaVersion === 1);
  boundedList(value.items, 1, 20);
  exactKeys(value.capabilities, ["revoke_one", "revoke_all"]);
  requireValue(value.capabilities.revoke_one === false && value.capabilities.revoke_all === false);
  const identifiers = new Set(); let current = 0, previousActivity = null;
  const items = value.items.map((item, index) => {
    exactKeys(item, ["id", "method", "device_label", "created_at", "authenticated_at", "last_activity_at", "idle_expires_at", "absolute_expires_at", "current"]);
    const id = accountOwner(item.id);
    requireValue(!identifiers.has(id)); identifiers.add(id);
    requireValue(["google", "password"].includes(item.method) && typeof item.current === "boolean");
    if (item.current) { current += 1; requireValue(index === 0); }
    const created = instant(item.created_at), authenticated = instant(item.authenticated_at), activity = instant(item.last_activity_at);
    const idle = instant(item.idle_expires_at), absolute = instant(item.absolute_expires_at);
    requireValue(created <= authenticated && authenticated <= activity && activity < idle && idle <= absolute);
    if (index > 1) requireValue(activity <= previousActivity);
    previousActivity = activity;
    return { id, method: item.method, device_label: deviceLabel(item.device_label),
      created_at: item.created_at, authenticated_at: item.authenticated_at, last_activity_at: item.last_activity_at,
      idle_expires_at: item.idle_expires_at, absolute_expires_at: item.absolute_expires_at, current: item.current };
  });
  requireValue(current === 1);
  return { schemaVersion: 1, items, capabilities: { revoke_one: false, revoke_all: false } };
}
