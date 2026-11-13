"""Actual synthetic Ed25519 bytes; modeled filesystem, not OS durability proof."""

import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
from retirement.checkpoint import (
    CheckpointUnavailable,
    MAX_FILE_BYTES,
    ProtectedFile,
    RECORD_BYTES,
    ZERO,
    decode,
)
from retirement.publisher import publish, signed_record

INSTALLATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
KEY_ID = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
COMMITMENT = b"k" * 32


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        # Synthetic test-only key is created in memory, never loaded from disk.
        self.private = Ed25519PrivateKey.generate()
        self.public = self.private.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self.genesis = self.record(0, ZERO, ZERO)
        self.first = self.record(1, b"a" * 32, hashlib.sha256(self.genesis).digest())
        self.second = self.record(2, b"b" * 32, hashlib.sha256(self.first).digest())
        self.protected = ProtectedFile(
            Path("synthetic-checkpoint").absolute(),
            owner_uid=1000,
            public_key=self.public,
            installation=INSTALLATION,
            key_id=KEY_ID,
            commitment=COMMITMENT,
        )

    def record(self, sequence, digest, previous, *, key=None):
        return signed_record(
            key or self.private,
            installation=INSTALLATION,
            key_id=KEY_ID,
            sequence=sequence,
            digest=digest,
            previous=previous,
            commitment=COMMITMENT,
        )

    def decode(self, raw):
        return decode(
            raw,
            self.public,
            installation=INSTALLATION,
            key_id=KEY_ID,
            commitment=COMMITMENT,
        )

    def read(self, content, *, full=False, identity=(1, 2)):
        before = SimpleNamespace(
            st_dev=identity[0], st_ino=identity[1], st_size=len(content)
        )
        with (
            patch.object(self.protected, "_open", return_value=(123, before)),
            patch.object(self.protected, "_unchanged") as unchanged,
            patch(
                "retirement.checkpoint.os.pread",
                create=True,
                side_effect=lambda fd, size, offset: content[offset : offset + size],
            ),
            patch("retirement.checkpoint.os.close"),
        ):
            value = self.protected.head(full=full)
            unchanged.assert_called_once()
            return value

    def test_fixed_record_exact_signed_genesis_and_full_chain(self):
        self.assertEqual(len(self.genesis), RECORD_BYTES)
        self.assertEqual(self.decode(self.genesis).sequence, 0)
        current = self.read(self.genesis + self.first + self.second, full=True)
        self.assertEqual(current.sequence, 2)
        self.assertEqual(current.event_digest, b"b" * 32)
        self.assertEqual(self.read(self.genesis + self.first + self.second), current)

    def test_runtime_requires_full_scan_and_same_inode_first(self):
        with self.assertRaises(CheckpointUnavailable):
            self.read(self.genesis)
        self.read(self.genesis, full=True)
        with self.assertRaises(CheckpointUnavailable):
            self.read(self.genesis, identity=(1, 3))

    def test_signature_substitution_genesis_partial_and_identity_denied(self):
        bad = bytearray(self.first)
        bad[60] ^= 1
        wrong = Ed25519PrivateKey.generate()
        for raw in (
            bytes(bad),
            self.first[:-1],
            self.first + b"x",
            self.record(1, b"a" * 32, ZERO, key=wrong),
        ):
            with self.subTest(size=len(raw)), self.assertRaises(CheckpointUnavailable):
                self.decode(raw)
        for changes in (
            {"installation": KEY_ID},
            {"key_id": INSTALLATION},
            {"commitment": b"x" * 32},
        ):
            args = dict(installation=INSTALLATION, key_id=KEY_ID, commitment=COMMITMENT)
            with self.assertRaises(CheckpointUnavailable):
                decode(self.genesis, self.public, **{**args, **changes})
        with self.assertRaises(CheckpointUnavailable):
            self.record(0, b"a" * 32, ZERO)

    def test_signed_skip_or_changed_previous_record_is_rejected(self):
        skipped = self.record(2, b"b" * 32, hashlib.sha256(self.genesis).digest())
        wrong_chain = self.record(1, b"a" * 32, b"x" * 32)
        for raw in (skipped, wrong_chain):
            with self.assertRaises(CheckpointUnavailable):
                self.read(self.genesis + raw, full=True)

    def test_restored_stale_database_or_missing_ack_cannot_be_current(self):
        head = self.decode(self.first)
        current = (INSTALLATION, KEY_ID, COMMITMENT, 1, b"a" * 32, 1, b"a" * 32, 0)
        with patch.object(self.protected, "head", return_value=head):
            for index, value in ((3, 0), (4, ZERO), (5, 0), (6, ZERO), (7, 1)):
                row = list(current)
                row[index] = value
                conn = SimpleNamespace(
                    execute=lambda *args: SimpleNamespace(fetchone=lambda: tuple(row))
                )
                with self.assertRaises(CheckpointUnavailable):
                    self.protected.require_current(conn)
            conn = SimpleNamespace(
                execute=lambda *args: SimpleNamespace(fetchone=lambda: current)
            )
            self.assertEqual(self.protected.require_current(conn), head)

    def test_actual_inode_append_only_failure_is_denied_not_assumed(self):
        # Unsupported ioctl/OS is deliberately false. No test sets chattr or
        # claims that mocked storage is actually append-only/durable.
        from retirement.checkpoint import append_only

        self.assertFalse(append_only(-1))


class PublisherTests(unittest.TestCase):
    setUp = CheckpointTests.setUp
    record = CheckpointTests.record
    decode = CheckpointTests.decode

    def prepare(self, *, after_append=False, size=RECORD_BYTES):
        old, new = self.decode(self.genesis), self.decode(self.first)
        self.events = []
        protected = self.protected
        row = (INSTALLATION, KEY_ID, COMMITMENT, 1, b"a" * 32, 0, ZERO, 0)
        protected.head = lambda: new if after_append or "write" in self.events else old
        protected._open = lambda **kwargs: (123, SimpleNamespace(st_size=size))
        protected._unchanged = lambda *args, **kwargs: self.events.append(
            "identity_checked"
        )

        def execute(sql, arguments=None):
            if "acknowledge_checkpoint" in sql:
                self.events.append("ack_sql_not_commit")
            return SimpleNamespace(fetchone=lambda: row)

        return protected, SimpleNamespace(execute=execute)

    def test_fsync_and_identity_precede_database_acknowledgement(self):
        protected, conn = self.prepare()

        def write(fd, raw):
            self.assertEqual(len(raw), RECORD_BYTES)
            self.events.append("write")
            return len(raw)

        with (
            patch("retirement.publisher.os.write", side_effect=write),
            patch(
                "retirement.publisher.os.fsync",
                side_effect=lambda fd: self.events.append("fsync"),
            ),
            patch("retirement.publisher.os.close"),
        ):
            result = publish(protected, conn, self.private)
        self.assertEqual(result.sequence, 1)
        self.assertLess(
            self.events.index("fsync"), self.events.index("ack_sql_not_commit")
        )
        self.assertLess(
            self.events.index("identity_checked"),
            self.events.index("ack_sql_not_commit"),
        )

    def test_append_before_ack_crash_reconciles_exact_bytes_without_resigning(self):
        protected, conn = self.prepare(after_append=True)
        with (
            patch("retirement.publisher.os.write") as write,
            patch("retirement.publisher.signed_record") as sign,
            patch("retirement.publisher.os.fsync") as sync,
            patch("retirement.publisher.os.close"),
        ):
            self.assertEqual(publish(protected, conn, self.private).sequence, 1)
            write.assert_not_called()
            sign.assert_not_called()
            sync.assert_called_once()
        self.assertIn("ack_sql_not_commit", self.events)

    def test_fsync_failure_partial_write_wrong_key_and_full_file_never_ack(self):
        for case in ("fsync", "partial", "wrong_key", "full"):
            protected, conn = self.prepare(
                size=MAX_FILE_BYTES if case == "full" else RECORD_BYTES
            )

            def write(fd, raw):
                self.events.append("write")
                return 1 if case == "partial" else len(raw)

            def sync(fd):
                if case == "fsync":
                    raise OSError("synthetic_fsync_failure")

            with (
                self.subTest(case=case),
                patch("retirement.publisher.os.write", side_effect=write),
                patch("retirement.publisher.os.fsync", side_effect=sync),
                patch("retirement.publisher.os.close"),
                self.assertRaises((CheckpointUnavailable, OSError)),
            ):
                publish(
                    protected,
                    conn,
                    (
                        Ed25519PrivateKey.generate()
                        if case == "wrong_key"
                        else self.private
                    ),
                )
            self.assertNotIn("ack_sql_not_commit", self.events)


if __name__ == "__main__":
    unittest.main()
