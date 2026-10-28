import assert from "node:assert/strict";
import test from "node:test";
import { ACCOUNT_DEFAULTS, DEVICE_DEFAULTS, clone } from "../src/settings/schema.js";
import { cancelPreferences, changePreference, confirmScope, dirtyScopes, initialPreferences, isDirty, loadPreferences, recoverAccountSave, replaceDraft } from "../src/settings/preferenceState.js";
import { CATEGORIES, sectionDefaults } from "../src/settings/controls.js";

const loaded = () => loadPreferences(initialPreferences(), { values: clone(ACCOUNT_DEFAULTS), revision: 1, capabilities: {} });
test("account draft, saved state and device draft remain distinct until confirmed", () => {
  let state = loaded(); state = changePreference(state, "account", "accent", "sage");
  state = changePreference(state, "device", "motion", "reduce");
  assert.equal(state.saved.account.accent, "pearl"); assert.equal(state.draft.account.accent, "sage");
  assert.deepEqual(dirtyScopes(state), { account: true, device: true });
  const submitted = clone(state.draft);
  state = confirmScope(state, submitted, "account", submitted.account);
  assert.deepEqual(dirtyScopes(state), { account: false, device: true });
  state = confirmScope(state, submitted, "device", submitted.device); assert.equal(isDirty(state), false);
});
test("late scope confirmation acknowledges its snapshot without clearing newer edits", () => {
  let state = changePreference(loaded(), "account", "accent", "sage"), submitted = clone(state.draft);
  state = changePreference(state, "account", "accent", "amber");
  state = changePreference(state, "account", "theme", "light");
  state = confirmScope(state, submitted, "account", submitted.account);
  assert.equal(state.saved.account.accent, "sage"); assert.equal(state.draft.account.accent, "amber");
  assert.equal(state.saved.account.theme, "opal"); assert.equal(state.draft.account.theme, "light"); assert.equal(isDirty(state), true);
});
test("cancel restores last confirmed values after an account-only partial success", () => {
  let state = changePreference(loaded(), "account", "accent", "sage"); state = changePreference(state, "device", "text_scale", 150);
  state = confirmScope(state, clone(state.draft), "account", state.draft.account); state = cancelPreferences(state);
  assert.equal(state.draft.account.accent, "sage"); assert.equal(state.draft.device.text_scale, 100); assert.equal(isDirty(state), false);
});
test("cancel restores last confirmed values after a device-only partial success", () => {
  let state = changePreference(loaded(), "account", "accent", "sage"); state = changePreference(state, "device", "text_scale", 150);
  state = confirmScope(state, clone(state.draft), "device", state.draft.device); state = cancelPreferences(state);
  assert.equal(state.draft.account.accent, "pearl"); assert.equal(state.draft.device.text_scale, 150); assert.equal(isDirty(state), false);
});
test("conflict reload can replace or deliberately retain account draft without dropping device changes", () => {
  let state = changePreference(loaded(), "account", "accent", "sage"); state = changePreference(state, "device", "text_scale", 150);
  const response = { values: { ...clone(ACCOUNT_DEFAULTS), theme: "light" }, revision: 2, capabilities: {} };
  const reapplied = loadPreferences(state, response, { reapply: true });
  assert.equal(reapplied.revision, 2); assert.equal(reapplied.saved.account.theme, "light");
  assert.equal(reapplied.draft.account.accent, "sage"); assert.equal(reapplied.draft.device.text_scale, 150);
  const replaced = loadPreferences(state, response); assert.equal(replaced.draft.account.theme, "light");
  assert.equal(replaced.draft.account.accent, "pearl"); assert.equal(replaced.draft.device.text_scale, 150);
});
test("section reset preserves other sections and offers separate undo versus global cancel outcomes", () => {
  let state = changePreference(loaded(), "account", "accent", "sage"); state = changePreference(state, "account", "grid", "minimal");
  const before = clone(state.draft), appearance = CATEGORIES.find((category) => category.id === "appearance");
  state = replaceDraft(state, sectionDefaults(appearance, ACCOUNT_DEFAULTS, DEVICE_DEFAULTS), "Reset");
  assert.equal(state.draft.account.accent, "pearl"); assert.equal(state.draft.account.grid, "minimal");
  assert.deepEqual(state.undo.draft, before); assert.equal(state.undo.label, "Reset");
  assert.equal(cancelPreferences(state).draft.account.grid, "subtle");
});
test("valid partial import changes only its allowed draft fields and preserves an undo snapshot", () => {
  let state = changePreference(loaded(), "account", "theme", "light"), before = clone(state.draft);
  state = replaceDraft(state, { account: { accent: "sage" }, device: { motion: "reduce" } }, "Preference import");
  assert.equal(state.draft.account.theme, "light"); assert.equal(state.draft.account.accent, "sage");
  assert.equal(state.draft.device.motion, "reduce"); assert.equal(state.saved.account.accent, "pearl"); assert.deepEqual(state.undo.draft, before);
});
test("invalid direct draft changes fail atomically before saved or preview values mutate", () => {
  const state = changePreference(loaded(), "account", "accent", "sage"), before = clone(state);
  assert.throws(() => replaceDraft(state, { account: { accent: "slate", owner: "foreign" } }, "Import"));
  assert.throws(() => changePreference(state, "device", "split_percent", -100)); assert.deepEqual(state, before);
});
test("lost-response readback matching the submitted snapshot confirms only that snapshot", () => {
  let state = changePreference(loaded(), "account", "accent", "sage");
  const snapshot = { ...clone(state.draft), revision: state.revision };
  state = changePreference(state, "account", "accent", "amber");
  const result = recoverAccountSave(state, snapshot, { values: snapshot.account, revision: 2, capabilities: {} });
  assert.equal(result.outcome, "confirmed"); assert.equal(result.state.revision, 2);
  assert.equal(result.state.saved.account.accent, "sage"); assert.equal(result.state.draft.account.accent, "amber");
  assert.equal(result.state.conflict, false); assert.equal(result.state.needsReload, false);
});
test("lost-response readback at unchanged revision and values permits a safe retry", () => {
  const state = changePreference(loaded(), "account", "accent", "sage"), snapshot = { ...clone(state.draft), revision: state.revision };
  const result = recoverAccountSave(state, snapshot, { values: clone(state.saved.account), revision: 1, capabilities: {} });
  assert.equal(result.outcome, "retryable"); assert.equal(result.state.revision, 1);
  assert.equal(result.state.draft.account.accent, "sage"); assert.equal(result.state.needsReload, false);
});
test("lost response followed by another writer requires explicit review before adopting its revision for a retry", () => {
  let state = changePreference(loaded(), "account", "accent", "sage"); state = changePreference(state, "device", "motion", "reduce");
  const snapshot = { ...clone(state.draft), revision: state.revision };
  const response = { values: { ...clone(state.saved.account), theme: "light" }, revision: 2, capabilities: {} };
  const result = recoverAccountSave(state, snapshot, response);
  assert.equal(result.outcome, "conflict"); assert.equal(result.state.conflict, true); assert.equal(result.state.needsReload, true);
  assert.equal(result.state.saved.account.theme, "light"); assert.equal(result.state.draft.account.theme, "opal");
  assert.equal(result.state.draft.account.accent, "sage"); assert.equal(result.state.draft.device.motion, "reduce");
  const reviewed = loadPreferences(result.state, response, { reapply: true });
  assert.equal(reviewed.conflict, false); assert.equal(reviewed.needsReload, false); assert.equal(reviewed.revision, 2);
  assert.equal(reviewed.draft.account.accent, "sage");
});
test("unexpected changed values without a revision increment still fail closed after a lost response", () => {
  const state = changePreference(loaded(), "account", "accent", "sage"), snapshot = { ...clone(state.draft), revision: state.revision };
  const result = recoverAccountSave(state, snapshot, { values: { ...clone(state.saved.account), theme: "light" }, revision: 1, capabilities: {} });
  assert.equal(result.outcome, "conflict"); assert.equal(result.state.needsReload, true);
});
