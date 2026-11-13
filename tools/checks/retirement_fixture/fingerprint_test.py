"""Synthetic pure draft checks only; no credentials or live module imports."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.fingerprints import IdentityKey, ISSUER, packed

KEY_ID = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class IdentityFingerprintTests(unittest.TestCase):
    def setUp(self):
        self.key = IdentityKey(KEY_ID, b"synthetic-key-only".ljust(32, b"0"))

    def test_same_stored_identity_survives_owner_uuid_changes(self):
        self.assertEqual(
            self.key.google(ISSUER, "ExactSubject"),
            self.key.google(ISSUER, "ExactSubject"),
        )
        self.assertEqual(len(self.key.mailbox("a@example.test").digest), 32)

    def test_subject_is_exact_without_case_or_unicode_folding(self):
        for first, second in (("Sub", "sub"), ("é", "e\u0301"), ("x", " x")):
            self.assertNotEqual(
                self.key.google(ISSUER, first), self.key.google(ISSUER, second)
            )

    def test_dots_and_plus_mailbox_suffixes_are_preserved(self):
        base = self.key.mailbox("a.b@example.test")
        self.assertNotEqual(base, self.key.mailbox("ab@example.test"))
        self.assertNotEqual(base, self.key.mailbox("a.b+tag@example.test"))

    def test_mailbox_must_already_be_the_actual_normalized_stored_key(self):
        for value in (
            "A@example.test",
            " a@example.test",
            "a@example.test ",
            "a",
            "a@@b",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.key.mailbox(value)

    def test_key_and_kind_and_tuple_boundaries_are_separate(self):
        other = IdentityKey(KEY_ID, b"other-synthetic-key".ljust(32, b"0"))
        self.assertNotEqual(
            self.key.mailbox("a@example.test"), other.mailbox("a@example.test")
        )
        self.assertNotEqual(
            self.key.google(ISSUER, "a@example.test"),
            self.key.mailbox("a@example.test"),
        )
        self.assertNotEqual(packed((b"ab", b"c")), packed((b"a", b"bc")))

    def test_google_gate_uses_both_subject_and_mailbox_fingerprints(self):
        values = self.key.google_grant_candidates(ISSUER, "Sub", "a@example.test")
        self.assertEqual(
            [value.kind for value in values], ["google_subject", "mailbox"]
        )

    def test_uncanonical_issuer_or_bad_key_is_denied_and_key_repr_is_private(self):
        with self.assertRaises(ValueError):
            self.key.google("accounts.google.com", "Sub")
        with self.assertRaises(ValueError):
            IdentityKey(KEY_ID, b"short")
        self.assertNotIn("synthetic", repr(self.key))


if __name__ == "__main__":
    unittest.main()
