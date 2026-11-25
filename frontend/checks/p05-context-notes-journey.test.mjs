import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { notesKey, notesTextDoubled, notesEvidence } from "./p05-context-notes-journey.mjs";

test("notes native Enter carries activation text while Tab and Escape remain physical key events", async () => {
  const calls = [];
  for (const key of ["Enter", "Tab", "Home", "ArrowDown", "Escape"]) await notesKey((...args) => calls.push(args), key);
  assert.deepEqual(calls, [["Enter", 0, "\r"], ["Tab", 0, undefined], ["Home", 0, undefined], ["ArrowDown", 0, undefined], ["Escape", 0, undefined]]);
});

test("doubled text requires measured legible baselines and a narrow actual doubling tolerance", () => {
  assert.equal(notesTextDoubled(14, 28), true); assert.equal(notesTextDoubled(16, 32.09), true);
  for (const pair of [[13, 26], [14, 14], [14, 27], [16, 32.11], [NaN, 28], [14, Infinity], ["14", 28]]) assert.equal(notesTextDoubled(...pair), false);
});

test("notes evidence refuses unfinished work, excess holds/calls, analysis or an unexercised chunk fault", () => {
  const state = { pending: [], calls: [{ action: "list" }, { action: "save" }, { action: "prepare" }], peakHeld: 1, chunkDenials: 1, geometry: { width: 320 } };
  const result = notesEvidence(state, 0);
  assert.equal(result.kind, "context_notes_mocked_api_only"); assert.equal(result.notes_requests, 3); assert.equal(result.mutations, 1);
  assert.equal(result.analysis_calls, 0); assert.equal(result.model_calls, 0);
  assert.deepEqual(result.out_of_band_callbacks, ["composer", "target", "history", "owner"]);
  assert.throws(() => notesEvidence(state, 1));
  for (const change of [{ pending: [() => {}] }, { calls: Array.from({ length: 81 }, () => ({ action: "list" })) }, { peakHeld: 5 }, { peakHeld: -1 }, { peakHeld: 0.5 }, { chunkDenials: 0 }])
    assert.throws(() => notesEvidence({ ...state, ...change }, 0));
});

test("notes journey is explicit and isolated with all canonical resource and failure thresholds retained", async () => {
  const source = await readFile(new URL("./p05-browser.mjs", import.meta.url), "utf8");
  assert.match(source, /const MAX_MS = 240000, MAX_REQUESTS = 900, MAX_API = 344;/);
  assert.match(source, /const NOTES_ONLY=JOURNEY==="context-notes";/);
  assert.match(source, /const notesFixture = NOTES_ONLY \? installContextNotesFixture\(fixture\) : null;/);
  assert.match(source, /if\(NOTES_ONLY\)contextNotesJourney=await runContextNotesChecks/);
  assert.match(source, /if \(JOURNEY === null\) \{/);
  for (const threshold of [/assert\.equal\(consoleLeaks,0\)/, /assert\.equal\(runtimeErrors,0\)/, /assert\.equal\(protocolFailures\.length,0\)/, /assert\.equal\(external\.length,0\)/]) assert.match(source, threshold);
  assert.match(source, /NOTES_ONLY && notesFixture\.blockChunk/);
  assert.match(source, /if \(NOTES_ONLY\) notesFixture\.chunkDenials\+\+;/);
});
