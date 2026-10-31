import assert from "node:assert/strict";
import test from "node:test";
import { canAccountAction, createActionProofVault, securityActionReducer as reduce, securityActionState, securityFailure } from "../src/settings/accountSecurityState.js";

const owner = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const token = "v2." + "a".repeat(43), current = { id, current: true, device_label: "Desktop browser" };
const action = { operation: "session_revoke", session: current };
const capabilities = { recent_proof: true, password_change: true, session_revoke: true, sessions_revoke_all: true };
const data = () => ({ profile: { capabilities: { ...capabilities } }, methods: { password: { linked: true, available: true }, capabilities: { ...capabilities } },
  sessions: { items: [current], capabilities: { revoke_one: true, revoke_all: true } } });
const confirmed = () => reduce(reduce(securityActionState(), { type: "verify" }), { type: "verified" });

test("security actions require actual available password method and both server capability snapshots", () => {
  for (const target of [action, { operation: "password_change" }, { operation: "sessions_revoke_all" }]) {
    assert.equal(canAccountAction(data(), target), true);
    for (const field of ["profile", "methods"]) {
      const value = data(); delete value[field]; assert.equal(canAccountAction(value, target), false);
      const disabled = data(); disabled[field].capabilities.recent_proof = false; assert.equal(canAccountAction(disabled, target), false);
      const unsupported = data(); unsupported[field].capabilities[target.operation] = false; assert.equal(canAccountAction(unsupported, target), false);
    }
    for (const key of ["linked", "available"]) for (const value of [false, undefined, 1, "true"]) {
      const snapshot = data(); snapshot.methods.password[key] = value; assert.equal(canAccountAction(snapshot, target), false);
    }
  }
  assert.equal(canAccountAction(data(), { operation: "password_add" }), false);
  assert.equal(canAccountAction(data(), { operation: "email_change" }), false);
});

test("session revocation additionally requires a current bounded list and exact target metadata", () => {
  for (const target of [action, { operation: "sessions_revoke_all" }]) {
    const missing = data(); missing.sessions = null; assert.equal(canAccountAction(missing, target), false);
    const disabled = data(); disabled.sessions.capabilities = { revoke_one: false, revoke_all: false }; assert.equal(canAccountAction(disabled, target), false);
  }
  assert.equal(canAccountAction(data(), { operation: "session_revoke", session: { ...current, id: owner } }), false);
  assert.equal(canAccountAction(data(), { operation: "session_revoke", session: { ...current, current: false } }), false);
  const noCurrent = data(); noCurrent.sessions.items = []; assert.equal(canAccountAction(noCurrent, { operation: "sessions_revoke_all" }), false);
});

test("proof vault is transient, at most five minutes, single-use and never serializable", () => {
  let now = 1000000;
  const vault = createActionProofVault(owner, action, () => ({ owner, active: true }), () => now);
  assert.equal(vault.store({ proof_token: token, expires_at: new Date(now + 600000).toISOString() }), true);
  assert.equal(vault.deadline(), now + 300000);
  assert.equal(JSON.stringify(vault), "{}");
  assert.equal(vault.take(action), token); assert.equal(vault.take(action), null); assert.equal(vault.deadline(), 0);
  assert.equal(vault.store({ proof_token: token, expires_at: new Date(now + 1000).toISOString() }), true);
  now += 1000; assert.equal(vault.take(action), null);
});

test("proof vault rejects wrong action/target, stale owner and pending sign-in without retaining the proof", () => {
  let identity = { owner, active: true }, now = 1000000;
  const vault = createActionProofVault(owner, action, () => identity, () => now);
  const store = () => vault.store({ proof_token: token, expires_at: new Date(now + 1000).toISOString() });
  for (const target of [{ operation: "sessions_revoke_all" }, { operation: "session_revoke", session: { id: owner } }, null]) {
    store(); assert.equal(vault.take(target), null); assert.equal(vault.take(action), null);
  }
  store(); identity = { owner: id, active: true }; assert.equal(vault.take(action), null);
  identity = { owner, active: true }; store(); identity.active = false; assert.equal(vault.take(action), null);
  assert.equal(store(), false); identity.active = true; assert.equal(vault.take(action), null);
  assert.equal(vault.store({ proof_token: "invalid", expires_at: new Date(now + 1000).toISOString() }), false);
});

test("a same-owner session CSRF replacement invalidates the old proof and permits only a fresh one", () => {
  const identity = { owner, active: true, csrfToken: "session-A" }, now = 1000000;
  const vault = createActionProofVault(owner, action, () => identity, () => now);
  vault.store({ proof_token: token, expires_at: new Date(now + 1000).toISOString() });
  identity.csrfToken = "session-B";
  assert.equal(vault.take(action), null);
  assert.equal(vault.store({ proof_token: token, expires_at: new Date(now + 1000).toISOString() }), true);
  assert.equal(vault.take(action), token);
});

test("fresh verification cannot itself confirm a mutation and duplicate submits cannot advance phases", () => {
  let state = securityActionState();
  assert.equal(reduce(state, { type: "mutate" }), state);
  state = reduce(state, { type: "verify" }); assert.equal(state.phase, "verifying");
  assert.equal(reduce(state, { type: "verify" }), state); assert.equal(reduce(state, { type: "mutate" }), state);
  state = reduce(state, { type: "verified", proof_token: token }); assert.equal(state.phase, "confirm");
  assert.doesNotMatch(JSON.stringify(state), /proof_token|v2\./);
  state = reduce(state, { type: "mutate" }); assert.equal(state.phase, "mutating");
  assert.equal(reduce(state, { type: "mutate" }), state);
  state = reduce(state, { type: "confirmed" }); assert.equal(state.phase, "done");
  assert.equal(reduce(state, { type: "interrupted" }), state);
});

test("every failed password verification requires a fresh challenge and never publishes raw errors", () => {
  for (const status of [0, 401, 403, 422, 429, 503]) {
    const state = reduce(reduce(securityActionState(), { type: "verify" }), { type: "verification-failed", error: { status, message: token } });
    assert.equal(state.phase, "verify"); assert.doesNotMatch(JSON.stringify(state), /v2\./);
    assert.equal(reduce(state, { type: "mutate" }), state);
  }
});

test("lost mutation responses and interrupted commits cannot replay or claim success", () => {
  for (const event of [{ type: "mutation-failed", error: { status: 0 } }, { type: "mutation-failed", error: { status: 503 } }, { type: "interrupted" }]) {
    const state = reduce(reduce(confirmed(), { type: "mutate" }), event);
    assert.equal(state.phase, "uncertain"); assert.equal(state.check, "");
    assert.equal(reduce(state, { type: "verify" }), state); assert.equal(reduce(state, { type: "mutate" }), state);
    assert.doesNotMatch(JSON.stringify(state), /confirmed":true|succeeded/);
  }
});

test("401 after an uncertain change never becomes success or a new proof", () => {
  let state = reduce(reduce(confirmed(), { type: "mutate" }), { type: "mutation-failed", error: { status: 0 } });
  state = reduce(state, { type: "check" }); state = reduce(state, { type: "check-failed", error: { status: 401 } });
  assert.equal(state.phase, "uncertain"); assert.equal(state.check, ""); assert.equal(reduce(state, { type: "mutate" }), state);
});

test("access reconciliation requires an explicit review before starting an entirely new verification", () => {
  let state = reduce(reduce(confirmed(), { type: "mutate" }), { type: "mutation-failed", error: { status: 0 } });
  state = reduce(reduce(state, { type: "check" }), { type: "checked", targetAbsent: false });
  assert.equal(state.phase, "review"); assert.equal(state.check, "active");
  assert.equal(reduce(state, { type: "mutate" }), state); assert.equal(reduce(state, { type: "verify" }), state);
  state = reduce(state, { type: "restart" }); assert.equal(state.phase, "verify");
});

test("an absent target is reported as inactive without crediting the ambiguous request", () => {
  let state = reduce(reduce(confirmed(), { type: "mutate" }), { type: "mutation-failed", error: { status: 0 } });
  state = reduce(reduce(state, { type: "check" }), { type: "checked", targetAbsent: true });
  assert.equal(state.phase, "review"); assert.equal(state.check, "absent");
  assert.equal(reduce(state, { type: "restart" }), state); assert.equal(reduce(state, { type: "interrupted" }), state);
});

test("auth refresh or capability loss discards confirmation instead of preserving reusable authority", () => {
  const state = reduce(confirmed(), { type: "interrupted" });
  assert.equal(state.phase, "verify"); assert.equal(reduce(state, { type: "mutate" }), state);
  assert.equal(reduce(confirmed(), { type: "expired" }).phase, "verify");
});

test("a confirmed read-only review survives capability loss without enabling mutation or fresh authority", () => {
  let state = reduce(reduce(confirmed(), { type: "mutate" }), { type: "mutation-failed", error: { status: 0 } });
  state = reduce(reduce(state, { type: "check" }), { type: "checked", targetAbsent: false });
  assert.equal(reduce(state, { type: "interrupted", preserveReview: true }), state);
  assert.equal(reduce(state, { type: "mutate" }), state);
  assert.equal(reduce(state, { type: "verify" }), state);
  assert.equal(reduce(state, { type: "interrupted", preserveReview: false }).phase, "verify");
});

test("all security failure feedback is fixed and excludes private payloads", () => {
  for (const phase of ["verification", "mutation"]) for (const status of [0, 401, 403, 404, 422, 429, 503]) {
    assert.doesNotMatch(securityFailure({ status, message: "Private SQL password " + token }, phase), /Private|SQL|v2\./);
  }
});
