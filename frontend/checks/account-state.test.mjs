import assert from "node:assert/strict";
import test from "node:test";
import { acceptsAccountSnapshot, accountFailure, createAccountRequestScope, nameEditor, nameEditorReducer as reduce } from "../src/settings/accountState.js";

const owner = "11111111-1111-4111-8111-111111111111";
const profile = (revision = 1, name = "Saved name") => ({ revision, user: { id: owner, name } });
const entered = () => reduce(nameEditor(profile()), { type: "edit", value: "My retained edit" });
const saving = () => reduce(entered(), { type: "save", name: "My retained edit" });
const failed = (status = 409) => reduce(saving(), { type: "failed", error: { status, message: "PRIVATE SERVER DETAIL" } });

test("owner scope cancels and refuses late reads during refresh, owner change and unmount", () => {
  let identity = { owner, active: true };
  const scope = createAccountRequestScope(owner, () => identity);
  const profileRead = scope.begin("profile"), methods = scope.begin("methods"), sessions = scope.begin("sessions");
  assert.ok(profileRead.current() && methods.current() && sessions.current());
  identity = { owner, active: false };
  assert.equal(profileRead.current(), false); assert.equal(scope.begin("name"), null);
  scope.abort();
  for (const read of [profileRead, methods, sessions]) assert.equal(read.signal.aborted, true);
  identity = { owner, active: true };
  assert.equal(profileRead.current(), false);
  const resumed = scope.begin("profile"); assert.equal(resumed.current(), true);
  identity = { owner: "22222222-2222-4222-8222-222222222222", active: true };
  assert.equal(resumed.current(), false); assert.equal(scope.begin("profile"), null);
  scope.dispose(); assert.equal(resumed.signal.aborted, true);
  identity = { owner, active: true };
  assert.equal(scope.begin("profile"), null);
});

test("replaced request cannot settle or clear a newer request for the same resource", () => {
  const scope = createAccountRequestScope(owner, () => ({ owner, active: true }));
  const first = scope.begin("profile"), second = scope.begin("profile"), methods = scope.begin("methods");
  assert.equal(first.signal.aborted, true); assert.equal(first.current(), false);
  first.finish(); assert.equal(second.current(), true); assert.equal(methods.current(), true);
  second.finish(); assert.equal(second.current(), false); assert.equal(methods.current(), true);
  scope.dispose();
});

test("effect cleanup and reactivation never revive an earlier request", () => {
  const scope = createAccountRequestScope(owner, () => ({ owner, active: true }));
  const first = scope.begin("profile"); scope.dispose(); scope.activate();
  assert.equal(first.current(), false); assert.equal(first.signal.aborted, true);
  assert.equal(scope.begin("profile").current(), true); scope.dispose();
});

test("same-owner session CSRF replacement fences results from the earlier authority pair", () => {
  const identity = { owner, active: true, csrfToken: "session-A" };
  const scope = createAccountRequestScope(owner, () => identity), first = scope.begin("proof");
  identity.csrfToken = "session-B";
  assert.equal(first.current(), false);
  assert.equal(scope.begin("proof").current(), true);
  scope.dispose();
});

test("CAS conflict retains text and cannot save until explicit reload and review", () => {
  let state = failed();
  assert.equal(state.stage, "blocked"); assert.equal(state.draft, "My retained edit"); assert.equal(state.base.revision, 1);
  assert.equal(reduce(state, { type: "save", name: "My retained edit" }), state);
  state = reduce(state, { type: "check" });
  state = reduce(state, { type: "checked", profile: profile(2, "Other tab") });
  assert.equal(state.stage, "review"); assert.equal(state.draft, "My retained edit"); assert.equal(state.base.revision, 1);
  assert.equal(reduce(state, { type: "save", name: "My retained edit" }), state);
  state = reduce(state, { type: "keep-edit" });
  assert.equal(state.stage, "editing"); assert.equal(state.base.revision, 2); assert.equal(state.draft, "My retained edit");
  state = reduce(state, { type: "save", name: state.draft });
  assert.equal(state.attempt.revision, 2); assert.equal(state.stage, "saving");
});

test("choosing saved name after conflict uses canonical text without issuing a mutation", () => {
  const checking = reduce(failed(), { type: "check" });
  const review = reduce(checking, { type: "checked", profile: profile(3, "Latest canonical") });
  const chosen = reduce(review, { type: "use-saved" });
  assert.equal(chosen.draft, "Latest canonical"); assert.equal(chosen.base.revision, 3);
  assert.equal(chosen.stage, "editing"); assert.equal(chosen.attempt, null);
});

test("lost response and invalid response require GET reconciliation and never blind replay", () => {
  for (const status of [0, 500, 503, null]) {
    let state = failed(status);
    assert.equal(state.reason, "uncertain"); assert.equal(state.stage, "blocked");
    assert.equal(state.draft, "My retained edit"); assert.doesNotMatch(state.error, /PRIVATE/);
    assert.equal(reduce(state, { type: "save", name: state.draft }), state);
    state = reduce(state, { type: "check" });
    state = reduce(state, { type: "checked", profile: profile(2, "My retained edit") });
    assert.equal(state.stage, "complete"); assert.equal(state.base.revision, 2);
  }
});

test("read after failed write can confirm a no-op, but never discard a newer entered edit", () => {
  let state = reduce(nameEditor(profile(4, "Already saved")), { type: "save", name: "Already saved" });
  state = reduce(state, { type: "failed", error: { status: 0 } });
  const blocked = state;
  state = reduce(reduce(state, { type: "check" }), { type: "checked", profile: profile(4, "Already saved") });
  assert.equal(state.stage, "complete");
  state = reduce(blocked, { type: "edit", value: "An even newer edit" });
  state = reduce(reduce(state, { type: "check" }), { type: "checked", profile: profile(5, "Already saved") });
  assert.equal(state.stage, "review"); assert.equal(state.draft, "An even newer edit");
});

test("failed reconciliation preserves text and remains blocked through repeated failures", () => {
  let state = failed(0);
  for (const status of [503, 429, 401]) {
    state = reduce(state, { type: "check" });
    state = reduce(state, { type: "check-failed", error: { status, message: "PRIVATE SERVER DETAIL" } });
    assert.equal(state.stage, "blocked"); assert.equal(state.draft, "My retained edit");
    assert.equal(reduce(state, { type: "save", name: state.draft }), state); assert.doesNotMatch(state.error, /PRIVATE/);
  }
});

test("reconciliation refuses a rolled-back revision or changed name without revision advance", () => {
  for (const snapshot of [profile(0, "Saved name"), profile(1, "Unexpected name at same revision")]) {
    const state = reduce(reduce(failed(0), { type: "check" }), { type: "checked", profile: snapshot });
    assert.equal(state.stage, "blocked"); assert.equal(state.base.revision, 1);
    assert.equal(state.draft, "My retained edit"); assert.equal(state.latest, null);
    assert.equal(reduce(state, { type: "keep-edit" }), state);
    assert.equal(reduce(state, { type: "save", name: state.draft }), state);
  }
});

test("the published profile guard also refuses contradictory, rolled-back and foreign snapshots", () => {
  const current = profile(4, "Canonical");
  assert.equal(acceptsAccountSnapshot(null, current), true);
  assert.equal(acceptsAccountSnapshot(current, profile(4, "Canonical")), true);
  assert.equal(acceptsAccountSnapshot(current, profile(5, "Confirmed change")), true);
  assert.equal(acceptsAccountSnapshot(current, profile(4, "Contradictory")), false);
  assert.equal(acceptsAccountSnapshot(current, profile(3, "Canonical")), false);
  assert.equal(acceptsAccountSnapshot(current, { ...profile(5, "Foreign"), user: { id: "other-owner", name: "Foreign" } }), false);
});

test("definitive input and throttle failures retain text without fake confirmation", () => {
  for (const status of [401, 403, 422, 429]) {
    const state = failed(status);
    assert.equal(state.stage, "editing"); assert.equal(state.draft, "My retained edit");
    assert.equal(state.base.user.name, "Saved name"); assert.doesNotMatch(state.error, /PRIVATE/);
  }
});

test("saving disables edits and ignores duplicate submits; only confirmed server text becomes saved", () => {
  let state = saving();
  assert.equal(reduce(state, { type: "edit", value: "Late changed name" }), state);
  assert.equal(reduce(state, { type: "save", name: "Late changed name" }), state);
  assert.equal(state.base.user.name, "Saved name");
  state = reduce(state, { type: "saved", profile: profile(2, "My retained edit") });
  assert.equal(state.stage, "complete"); assert.equal(state.base.user.name, "My retained edit");
  assert.equal(reduce(state, { type: "failed", error: { status: 0 } }), state);
});

test("account errors never copy arbitrary server or network details", () => {
  for (const status of [0, 400, 401, 403, 409, 422, 429, 500]) {
    assert.doesNotMatch(accountFailure({ status, message: "Private customer records / SQL / token" }), /Private|SQL|token/);
  }
});
