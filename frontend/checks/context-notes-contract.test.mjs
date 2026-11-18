import assert from "node:assert/strict";
import test from "node:test";
import { decodeNoteList, decodeNote, decodePreparedNote, decodeForgottenNote, validNoteBody, validNoteDraft, validNoteLabel } from "../src/features/contextNotes/contract.js";
import { ownerId, scope, library, readReply, prepared, item, note, envelope, noteId, otherId, unavailable } from "./context-notes-fixture.mjs";

test("available metadata contains no body; unavailable metadata exposes only the generic projection", () => {
  const result = decodeNoteList(library(), ownerId); assert.equal(Object.hasOwn(result.items[0], "body"), false);
  assert.deepEqual(result.items[1], unavailable());
  const noGrant = library(); noGrant.scope.can_use = false; noGrant.items = [unavailable()]; assert.equal(decodeNoteList(noGrant, ownerId).scope.can_use, false);
  for (const mutate of [v => { v.items[0].body = "private"; }, v => { v.items[1].label = "Old confidential label"; }, v => { v.items[1].created_at = item().created_at; },
    v => { v.items.push(item()); }, v => { v.scope.can_use = false; }, v => { v.limits.active_notes = 21; }, v => { v.items = Array(1); }]) {
    const value = library(); mutate(value); assert.throws(() => decodeNoteList(value, ownerId), { code: "invalid_response" });
  }
});

test("envelopes reject borrowed owners, unknown authority, accessors and enabled execution", () => {
  for (const mutate of [v => { v.owner_id = otherId; }, v => { v.role = "admin"; }, v => { v.scope.dataset = "private"; },
    v => { v.execution_enabled = true; }, v => { v.unverified = false; }, v => { v.schemaVersion = true; }, v => { v.items[0].revision = true; },
    v => { v.items[0].revision = 9007199254740992; }]) { const value = library(); mutate(value); assert.throws(() => decodeNoteList(value, ownerId)); }
  let read = false; const value = library(); Object.defineProperty(value.scope, "id", { get() { read = true; return scope.id; } });
  assert.throws(() => decodeNoteList(value, ownerId)); assert.equal(read, false);
});

test("labels count code points while bodies count UTF16 units and independent UTF8 bytes without normalization", () => {
  assert.equal(validNoteLabel("😀".repeat(120)), true); assert.equal(validNoteLabel("😀".repeat(121)), false);
  assert.equal(validNoteBody("x".repeat(2000)), true); assert.equal(validNoteBody("x".repeat(2001)), false);
  assert.equal(validNoteBody("😀".repeat(512)), true); assert.equal(validNoteBody("😀".repeat(513)), false);
  assert.equal(validNoteDraft("😀".repeat(1000)), true); assert.equal(validNoteDraft("😀".repeat(1001)), false);
  assert.equal(validNoteBody("\tA\nB  "), true); assert.equal(validNoteLabel(" A"), false); assert.equal(validNoteLabel("A "), false);
  for (const separator of ["\u2028", "\u2029"]) { assert.equal(validNoteLabel(`a${separator}b`), false); assert.equal(validNoteBody(`a${separator}b`), true); }
  const value = readReply(); value.note.body = " e\u0301\n  "; assert.equal(decodeNote(value, ownerId, scope).note.body, value.note.body);
  for (const bad of ["\r", "\0", "\u007f", "\u0085", "\u200b", "\u202e", "\u2066", "\ufeff", "\ud800"]) {
    assert.equal(validNoteBody(`a${bad}b`), false); assert.equal(validNoteDraft(`a${bad}b`), false); assert.equal(validNoteLabel(`a${bad}b`), false);
  }
});

test("full reads bind item, revision, timestamps and current source scope; invalid dates fail", () => {
  assert.equal(decodeNote(readReply(), ownerId, scope, item()).note.id, noteId);
  for (const mutate of [v => { v.note.id = otherId; }, v => { v.note.revision++; }, v => { v.scope.id = "b".repeat(64); }]) {
    const value = readReply(); mutate(value); assert.throws(() => decodeNote(value, ownerId, scope, item()), { status: 409 });
  }
  for (const mutate of [v => { v.note.label = "Changed without revision"; }, v => { v.note.updated_at = "2026-02-30T10:00:00Z"; },
    v => { v.note.created_at = "2026-12-01T00:00:00Z"; }, v => { v.note.created_at = "2026-11-17T10:00:00"; }]) {
    const value = readReply(); mutate(value); assert.throws(() => decodeNote(value, ownerId, scope, item()), { code: "invalid_response" });
  }
});

test("preparation requires the exact current saved body and source; deletion returns only advanced revision", () => {
  assert.deepEqual(decodePreparedNote(prepared(), ownerId, scope, note()), prepared());
  for (const mutate of [v => { v.draft += " altered"; }, v => { v.source.revision++; }, v => { v.requires_review = false; }, v => { v.source.body = "private"; }]) {
    const value = prepared(); mutate(value); assert.throws(() => decodePreparedNote(value, ownerId, scope, note()));
  }
  const value = envelope({ deleted: { id: noteId, revision: 3 } }); assert.equal(decodeForgottenNote(value, ownerId, scope, item()).deleted.revision, 3);
  value.deleted.body = "old content"; assert.throws(() => decodeForgottenNote(value, ownerId, scope, item()));
});
