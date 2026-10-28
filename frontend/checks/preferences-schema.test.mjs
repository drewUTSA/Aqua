import assert from "node:assert/strict";
import test from "node:test";
import { ACCOUNT_DEFAULTS, ACCOUNT_RULES, DEVICE_DEFAULTS, DEVICE_RULES, clone, equal, exportPreferences, parseImport, preferenceResponse, validateValues } from "../src/settings/schema.js";
import { readDevicePreferences, saveDevicePreferences, purgeDevicePreferences } from "../src/settings/deviceStore.js";

const portable = (account = {}, device) => JSON.stringify({ schemaVersion: 1, account, ...(device ? { device } : {}) });
test("approved account and optional device values roundtrip without private or permission fields", () => {
  const account = { ...clone(ACCOUNT_DEFAULTS), accent: "sage", sidebar_sections: ["prompts", "recents"] };
  const device = { ...clone(DEVICE_DEFAULTS), text_scale: 150, motion: "reduce" };
  assert.deepEqual(parseImport(exportPreferences(account, device)), { schemaVersion: 1, account, device });
  assert.deepEqual(parseImport(exportPreferences(account)), { schemaVersion: 1, account });
  assert.equal(Object.hasOwn(JSON.parse(exportPreferences(account)), "device"), false);
});
test("partial import omits values without filling or resetting the existing draft", () => {
  const parsed = parseImport(portable({ accent: "amber" }, { text_scale: 125 }));
  assert.deepEqual(parsed.account, { accent: "amber" }); assert.deepEqual(parsed.device, { text_scale: 125 });
  assert.deepEqual(ACCOUNT_DEFAULTS.accent, "pearl");
});
for (const [name, value] of Object.entries({
  "malformed JSON": "{", "no schema": '{"account":{}}', "unknown schema": '{"schemaVersion":2,"account":{}}',
  "boolean schema": '{"schemaVersion":true,"account":{}}', "missing account": '{"schemaVersion":1}',
  "unknown envelope key": '{"schemaVersion":1,"account":{},"role":"admin"}',
  "prototype envelope": '{"schemaVersion":1,"account":{},"__proto__":{}}',
  "prototype account": '{"schemaVersion":1,"account":{"__proto__":{"role":"admin"}}}',
  "constructor": '{"schemaVersion":1,"account":{"constructor":{"prototype":{}}}}',
  "owner": portable({ owner: "foreign" }), "role": portable({ role: "admin" }), "data access": portable({ dataset_grants: ["all"] }),
  "consent": portable({ consent: true }), "notification permission": portable({ notifications: true }), "instructions": portable({ personal_instructions: "secret" }),
  "script": portable({ accent: "<script>alert(1)</script>" }), "CSS": portable({ theme: "url(https://invalid.example/a.css)" }),
  "array object": portable([]), "nested value": portable({ theme: { value: "opal" } }), "null": portable(null),
  "wrong scope": portable({}, { theme: "light" }), "boolean number": portable({ recents_count: true }),
  "fractional number": portable({ table_page_size: 25.1 }), "numeric string": portable({ recents_count: "10" }),
  "out of range": portable({}, { split_percent: 99 }), "unsupported text scale": portable({}, { text_scale: 101 }),
  "unknown zone": portable({ timezone: "https://invalid.example/timezone" }), "duplicate order": portable({ sidebar_sections: ["recents", "recents"] }),
  "foreign section": portable({ sidebar_sections: ["admin"] }), "nonarray section": portable({ sidebar_sections: "recents" }),
  "duplicate envelope": '{"schemaVersion":1,"account":{"accent":"sage"},"account":{"accent":"amber"}}',
  "escaped duplicate": '{"schemaVersion":1,"account":{"accent":"sage","\\u0061ccent":"amber"}}',
  "duplicate schema": '{"schemaVersion":2,"schemaVersion":1,"account":{}}',
  "deep": '{"schemaVersion":1,"account":{"theme":{"a":{"b":{"c":{"d":{}}}}}}}',
  "oversized bytes": portable({ theme: "💧".repeat(20000) }), "trailing data": portable({}) + " true"
})) test(`import rejects ${name} atomically`, () => {
  const draft = { ...clone(ACCOUNT_DEFAULTS), accent: "slate" }, snapshot = clone(draft);
  assert.throws(() => parseImport(value)); assert.deepEqual(draft, snapshot); assert.equal({}.role, undefined);
});
test("all advertised finite values validate; number and bool types remain strict", () => {
  for (const [scope, rules, defaults] of [["account", ACCOUNT_RULES, ACCOUNT_DEFAULTS], ["device", DEVICE_RULES, DEVICE_DEFAULTS]]) {
    for (const [key, rule] of Object.entries(rules)) for (const value of rule.values || [rule.default]) {
      const allowed = rule.kind === "order" ? [value] : value;
      assert.deepEqual(validateValues({ ...defaults, [key]: allowed }, scope)[key], allowed);
    }
  }
  assert.throws(() => validateValues({ ...ACCOUNT_DEFAULTS, suggestions: "true" }, "account"));
  assert.throws(() => validateValues({ ...ACCOUNT_DEFAULTS, recents_count: true }, "account"));
});
test("canonical response requires complete supported schema, revision and safe capabilities", () => {
  const response = { schemaVersion: 1, revision: 3, values: clone(ACCOUNT_DEFAULTS), capabilities: { account_security: false, interface_languages: ["en"] } };
  assert.deepEqual(preferenceResponse(response), response);
  for (const bad of [{ ...response, schemaVersion: 2 }, { ...response, revision: -1 }, { ...response, revision: Number.MAX_SAFE_INTEGER + 1 },
    { ...response, values: {} }, { ...response, values: { ...response.values, admin: true } }, { ...response, capabilities: { api_key: "hidden" } }]) {
    assert.throws(() => preferenceResponse(bad));
  }
});
test("semantic equality ignores object serialization order but preserves section order", () => {
  assert.equal(equal({ theme: "opal", accent: "sage" }, { accent: "sage", theme: "opal" }), true);
  assert.equal(equal(["recents", "prompts"], ["prompts", "recents"]), false);
});
function memoryStore() {
  const values = new Map(); return { getItem: (key) => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key), values };
}
test("device preferences use isolated owner keys and confirmed local writes", () => {
  const storage = memoryStore(), values = { ...clone(DEVICE_DEFAULTS), motion: "reduce" };
  saveDevicePreferences("account-a", values, storage);
  assert.deepEqual(readDevicePreferences("account-a", storage).values, values);
  assert.deepEqual(readDevicePreferences("account-b", storage).values, DEVICE_DEFAULTS);
  purgeDevicePreferences("account-a", storage); assert.deepEqual(readDevicePreferences("account-a", storage).values, DEVICE_DEFAULTS);
});
test("future or unsupported saved device values remain intact and block destructive overwrite", () => {
  for (const record of [{ schemaVersion: 2, values: { future: true } }, { schemaVersion: 1, values: { future: true } },
    { schemaVersion: 1, values: { motion: "future-option" } }]) {
    const storage = memoryStore(), key = "aqua-preferences-device:v1:account-a", text = JSON.stringify(record);
    storage.setItem(key, text); assert.equal(readDevicePreferences("account-a", storage).writable, false);
    assert.throws(() => saveDevicePreferences("account-a", DEVICE_DEFAULTS, storage)); assert.equal(storage.getItem(key), text);
  }
});
test("blocked or silently discarded local writes never claim persistence", () => {
  const blocked = { getItem() { return null; }, setItem() { throw new Error("blocked"); } };
  assert.throws(() => saveDevicePreferences("account", DEVICE_DEFAULTS, blocked));
  assert.throws(() => saveDevicePreferences("account", DEVICE_DEFAULTS, { getItem: () => null, setItem() {} }));
});
