"""Actual pure opaque publication boundaries; no DB/session integration claim."""

import hashlib
import hmac
from pathlib import Path
import struct
import sys
import unittest
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.revision import DOMAIN, history_revision

OWNER = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OTHER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SECRET = "synthetic-existing-session-secret-" * 2


class RevisionTests(unittest.TestCase):
    def test_exact_domain_owner_bytes_and_bigendian_generation(self):
        expected = hmac.new(
            SECRET.encode(),
            DOMAIN + UUID(OWNER).bytes + struct.pack("!Q", 7),
            hashlib.sha256,
        ).hexdigest()
        self.assertEqual(history_revision(SECRET, OWNER, 7), expected)
        self.assertRegex(expected, r"^[a-f0-9]{64}$")

    def test_owner_generation_and_key_changes_invalidate_publication(self):
        first = history_revision(SECRET, OWNER, 1)
        for args in (
            (SECRET, OWNER, 2),
            (SECRET, OTHER, 1),
            (SECRET + "changed", OWNER, 1),
        ):
            self.assertNotEqual(first, history_revision(*args))
        self.assertEqual(first, history_revision(SECRET, OWNER, 1))

    def test_missing_noncanonical_and_boolean_or_out_of_range_inputs_fail_closed(self):
        for owner in (None, OWNER.upper(), "", "opaque-client-owner"):
            with self.assertRaises((ValueError, TypeError, AttributeError)):
                history_revision(SECRET, owner, 1)
        for generation in (None, True, 0, -1, 9007199254740992, "1"):
            with self.assertRaises(ValueError):
                history_revision(SECRET, OWNER, generation)
        for secret in (None, "short", "\ud800" * 32):
            with self.assertRaises(ValueError):
                history_revision(secret, OWNER, 1)


if __name__ == "__main__":
    unittest.main()
