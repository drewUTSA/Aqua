"""Synthetic metadata codec checks; SQL parity and durable storage unrun."""

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.fingerprints import IdentityKey
from retirement import pages

KEY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"


class PageTests(unittest.TestCase):
    def setUp(self):
        self.key = IdentityKey(KEY, b"synthetic-key".ljust(32, b"0"))

    def payload(self, n=0):
        return pages.encode("d" * 64, self.key.mailbox(f"owner{n}@example.test"))

    def test_fixed_width_roundtrip_contains_only_keyed_commitment(self):
        item = self.payload()
        dataset, fingerprint = pages.decode(item)
        self.assertEqual(len(item), 114)
        self.assertEqual(dataset, "d" * 64)
        self.assertEqual(fingerprint, self.key.mailbox("owner0@example.test"))
        self.assertNotIn(b"owner", item)
        self.assertNotIn(b"example.test", item)

    def test_canonical_set_is_sorted_deduplicated_and_paged(self):
        values = [self.payload(n) for n in range(129)]
        first = pages.manifest(values)
        second = pages.manifest(list(reversed(values)) + values[:3])
        self.assertEqual(first, second)
        self.assertEqual((first.count, len(first.pages)), (129, 2))
        self.assertEqual([len(page) for page in first.pages], [128, 1])

    def test_empty_manifest_and_changed_payload_have_distinct_roots(self):
        empty = pages.manifest([])
        self.assertEqual((empty.count, empty.root, empty.pages), (0, pages.INITIAL, ()))
        self.assertNotEqual(
            pages.manifest([self.payload(1)]).root,
            pages.manifest([self.payload(2)]).root,
        )

    def test_version_width_kind_dataset_and_order_are_validated(self):
        original = self.payload()
        for changed in (
            original[:-1],
            b"\x02" + original[1:],
            original[:81] + b"\x03" + original[82:],
            original[:1] + b"Z" + original[2:],
        ):
            with self.subTest(size=len(changed)), self.assertRaises(ValueError):
                pages.decode(changed)
        with self.assertRaises(ValueError):
            pages.page_digest(pages.INITIAL, 0, (original, original))


if __name__ == "__main__":
    unittest.main()
