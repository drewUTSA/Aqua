"""Standard-library-only P10a policy checks, also collected by pytest."""

import unittest

from account.policy import (
    CAPABILITIES,
    device_label,
    digest,
    display_name,
    target_digest,
)

ID = "00000000-0000-4000-8000-000000000001"


class AccountPolicyTests(unittest.TestCase):
    def test_profile_is_normalized_bounded_single_line_text(self):
        self.assertEqual(display_name("  Jose\u0301  "), "José")
        self.assertEqual(display_name("A" * 120), "A" * 120)
        for value in [
            None,
            True,
            4,
            [],
            {},
            "",
            " " * 2,
            "x" * 121,
            "a\nb",
            "a\x00b",
            "a\u202eb",
            "a\u200bb",
            "a\ud800b",
        ]:
            with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                display_name(value)

    def test_action_targets_cannot_cross_operations_or_use_unknown_properties(self):
        self.assertNotEqual(
            target_digest("session_revoke", ID), target_digest("google_unlink", ID)
        )
        self.assertEqual(len(target_digest("email_change", "a@example.invalid")), 32)
        for operation, target in [
            ("grant", None),
            (True, None),
            ("google_link", ID),
            ("session_revoke", "bad"),
            ("session_revoke", {}),
            ("email_change", "A@example.invalid"),
            ("email_change", "a@b\n"),
            ("email_change", "a@@b"),
        ]:
            with self.subTest(operation=operation), self.assertRaises(ValueError):
                target_digest(operation, target)

    def test_profile_rejects_unicode_line_breaks_without_rejecting_unicode_names(self):
        for separator in ["\u2028", "\u2029"]:
            for value in [
                "First" + separator + "Last",
                separator + "Name",
                "Name" + separator,
            ]:
                with self.subTest(value=repr(value)), self.assertRaises(ValueError):
                    display_name(value)
        for value, expected in [
            ("  Ame\u0301lie Dupont  ", "Amélie Dupont"),
            ("李 小龍", "李 小龍"),
            ("مريم أحمد", "مريم أحمد"),
            ("Nneka\u00a0Okafor", "Nneka\u00a0Okafor"),
        ]:
            with self.subTest(value=value):
                self.assertEqual(display_name(value), expected)

    def test_proof_digests_and_device_labels_do_not_accept_arbitrary_data(self):
        self.assertEqual(digest(b"a" * 32), b"a" * 32)
        for value in ["a" * 32, b"a" * 31, bytearray(b"a" * 32), None]:
            with self.assertRaises(ValueError):
                digest(value)
        self.assertEqual(device_label("  Desktop browser  "), "Desktop browser")
        for value in [None, "", "x" * 121, "bad\r\nHeader", "device\u202e"]:
            self.assertEqual(device_label(value), "Unknown device")

    def test_future_sensitive_capabilities_remain_disabled(self):
        self.assertTrue(CAPABILITIES["profile_edit"])
        for key, enabled in CAPABILITIES.items():
            if key not in {
                "profile_edit",
                "method_list",
                "session_list",
                "in_app_notifications",
            }:
                self.assertFalse(enabled, key)


if __name__ == "__main__":
    unittest.main()
