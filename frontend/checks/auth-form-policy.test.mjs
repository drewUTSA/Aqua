import test from "node:test";
import assert from "node:assert/strict";
import { validateNewPassword, passwordFailureMessage } from "../src/components/auth/authFormPolicy.js";

test("new password guidance uses NFC code points and accepts passphrases without composition rules", () => {
  for (const password of ["a".repeat(15), "A".repeat(128), "🦦".repeat(128), "a calm finance workspace", "e\u0301".repeat(15)]) {
    assert.equal(validateNewPassword(password, password.normalize("NFC")), "");
  }
  for (const password of ["a".repeat(14), "a".repeat(129), "🦦".repeat(129), "e\u0301".repeat(14)]) {
    assert.match(validateNewPassword(password, password), /15–128/);
  }
  assert.match(validateNewPassword("a calm finance workspace", "another calm workspace"), /do not match/);
});

test("UI failure copy never reflects hostile server error bodies, user inputs or tokens", () => {
  const canary = '<img onerror="alert(1)"> synthetic-email@example.invalid secret-token';
  for (const status of [0, 400, 401, 403, 422, 429, 500, 503]) {
    const message = passwordFailureMessage({ status, message: canary, detail: canary, code: canary });
    assert.doesNotMatch(message, /img|onerror|alert|synthetic|example\.invalid|secret-token/);
    assert.ok(message.length < 250);
  }
  assert.match(passwordFailureMessage({ code: "invalid_proof" }), /already used/);
  assert.match(passwordFailureMessage({ status: 429 }), /wait/);
  assert.match(passwordFailureMessage({ status: 403 }), /fresh attempt/);
});
