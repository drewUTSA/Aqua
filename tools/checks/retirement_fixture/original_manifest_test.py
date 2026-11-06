"""Pure original-byte persistence contract, not application/restore activation."""

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.fingerprints import IdentityKey, ISSUER
from retirement.intents import Intent
from retirement.original_manifest import (
    HEADER_BYTES,
    MAX_ORIGINAL_BYTES,
    ManifestUnavailable,
    encode_original,
    decode_original,
)
from retirement.pages import INITIAL, Manifest, encode, manifest

INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
OWNER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
INTENT = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
JOB = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
KEY = IdentityKey(INSTALLATION, b"synthetic-original-key".ljust(32, b"0"))
CREATED = datetime(2026, 10, 30, 12, 34, 56, 123456, tzinfo=timezone.utc)


class OriginalManifestTests(unittest.TestCase):
    def setUp(self):
        self.value = manifest(
            (
                encode("a" * 64, KEY.google(ISSUER, "SyntheticOriginal")),
                encode("a" * 64, KEY.mailbox("owner@example.test")),
                encode("b" * 64, KEY.google(ISSUER, "SyntheticOther")),
            )
        )
        self.record = Intent(
            INSTALLATION,
            OWNER,
            INTENT,
            JOB,
            "account_v1",
            CREATED,
            2,
            3,
            1,
            True,
            fingerprint_count=self.value.count,
            fingerprint_root=self.value.root,
        )
        self.raw = encode_original(self.record, self.value, key_id=KEY.key_id)

    def test_original_bytes_round_trip_exact_owner_job_time_floors_and_metadata(self):
        self.assertEqual(len(self.raw), HEADER_BYTES + self.value.count * 114)
        self.assertEqual(
            decode_original(self.raw, self.record, key_id=KEY.key_id), self.value
        )
        self.assertEqual(
            self.raw, encode_original(self.record, self.value, key_id=KEY.key_id)
        )
        self.assertNotIn(b"owner@example.test", self.raw)
        self.assertNotIn(b"SyntheticOriginal", self.raw)

    def test_history_empty_manifest_is_exact_original_header(self):
        record = Intent(
            INSTALLATION, OWNER, INTENT, JOB, "chat_history_v1", CREATED, 2, 2, 0, False
        )
        value = manifest(())
        raw = encode_original(record, value, key_id=KEY.key_id)
        self.assertEqual(len(raw), HEADER_BYTES)
        self.assertEqual(decode_original(raw, record, key_id=KEY.key_id), value)

    def test_substituted_owner_job_intent_timestamp_or_floor_cannot_be_reused(self):
        for changes in (
            {"owner": INSTALLATION},
            {"job": OWNER},
            {"intent": OWNER},
            {"created_at": CREATED + timedelta(microseconds=1)},
            {"history_floor": 4},
            {"privacy_floor": 4},
            {"auth_floor": 2},
        ):
            with self.subTest(changes=changes), self.assertRaises(ManifestUnavailable):
                decode_original(
                    self.raw, replace(self.record, **changes), key_id=KEY.key_id
                )

    def test_changed_count_root_order_duplicates_trailing_and_truncation_are_denied(
        self,
    ):
        wrong_count, wrong_root = bytearray(self.raw), bytearray(self.raw)
        wrong_count[108] ^= 1
        wrong_root[140] ^= 1
        entries = self.raw[HEADER_BYTES:]
        wrong_order = self.raw[:HEADER_BYTES] + entries[-114:] + entries[:-114]
        duplicate = (
            self.raw[:HEADER_BYTES] + entries[:114] + entries[:114] + entries[228:]
        )
        for raw in (
            bytes(wrong_count),
            bytes(wrong_root),
            wrong_order,
            duplicate,
            self.raw + b"x",
            self.raw[:-1],
        ):
            with self.assertRaises(ManifestUnavailable):
                decode_original(raw, self.record, key_id=KEY.key_id)

    def test_wrong_key_generation_and_noncanonical_declared_manifest_fail_before_store(
        self,
    ):
        for value in (
            Manifest(self.value.count, self.value.root, iter(self.value.pages)),
            Manifest(1, self.value.root, self.value.pages),
            Manifest(self.value.count, INITIAL, self.value.pages),
        ):
            with self.assertRaises(ManifestUnavailable):
                encode_original(self.record, value, key_id=KEY.key_id)
        for operation in (
            lambda: encode_original(self.record, self.value, key_id=OWNER),
            lambda: decode_original(self.raw, self.record, key_id=OWNER),
        ):
            with self.assertRaises(ManifestUnavailable):
                operation()

    def test_storage_body_cap_is_enforced_before_decoded_page_allocation(self):
        with self.assertRaises(ManifestUnavailable):
            decode_original(
                b"x" * (MAX_ORIGINAL_BYTES + 1), self.record, key_id=KEY.key_id
            )
        for raw in (None, bytearray(self.raw), self.raw[:140]):
            with self.assertRaises(ManifestUnavailable):
                decode_original(raw, self.record, key_id=KEY.key_id)


if __name__ == "__main__":
    unittest.main()
