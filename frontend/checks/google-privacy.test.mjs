import assert from "node:assert/strict";
import test from "node:test";
import { disableGoogleAutoSelect } from "../src/services/googleIdentity.js";

test("a blocked Google cleanup cannot prevent local sign-out or recovery", (t) => {
  const original = globalThis.google;
  t.after(() => { if (original === undefined) delete globalThis.google; else globalThis.google = original; });
  globalThis.google = { accounts: { id: { disableAutoSelect() { throw new DOMException("Storage access blocked", "SecurityError"); } } } };
  assert.doesNotThrow(() => disableGoogleAutoSelect());
});
