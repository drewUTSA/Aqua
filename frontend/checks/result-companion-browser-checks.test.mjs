import assert from "node:assert/strict";
import test from "node:test";
import { readFile } from "node:fs/promises";
import { resultCompanionKey, resultCompanionDoubledText } from "./result-companion-browser-checks.mjs";

test("native Enter has an activation character while Tab, field arrows and Escape retain their semantics", async () => {
  const calls = [];
  for (const key of ["Enter", "Tab", "Home", "ArrowDown", "Escape"]) await resultCompanionKey((...args) => calls.push(args), key);
  assert.deepEqual(calls, [["Enter", 0, "\r"], ["Tab", 0, undefined], ["Home", 0, undefined], ["ArrowDown", 0, undefined], ["Escape", 0, undefined]]);
});

test("doubled-text evidence requires a legible measured baseline and exact two-times scaling", () => {
  assert.equal(resultCompanionDoubledText(14, 28), true); assert.equal(resultCompanionDoubledText(16, 32.09), true);
  for (const pair of [[13,26],[14,14],[14,27],[16,32.11],[NaN,28],[14,Infinity],["14",28]]) assert.equal(resultCompanionDoubledText(...pair), false);
});

test("new journey is an explicit isolated branch with the retained shared resource ceilings", async () => {
  const source = await readFile(new URL("./p05-browser.mjs", import.meta.url), "utf8");
  assert.match(source, /const MAX_MS = 240000, MAX_REQUESTS = 900, MAX_API = 320;/);
  assert.match(source, /RESULT_ONLY=JOURNEY==="result-companion"/);
  assert.match(source, /const resultFixture = RESULT_ONLY \? installResultCompanionFixture\(fixture\) : null;/);
  assert.match(source, /if\(RESULT_ONLY\)resultCompanionJourney=await runResultCompanionChecks/);
  assert.match(source, /if \(JOURNEY === null\) \{/);
});
