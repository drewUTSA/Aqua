"""Bounded custody preserves byte order, authenticated feedback and old recovery files."""

from contextlib import closing
from hashlib import sha256
import os
from pathlib import Path
import shutil
import sqlite3
import tempfile
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .rotating_physical_wal import RotatingWal
from .rotating_receiver import ForwardReceiver
from .wal_store import WalIdentity, WalStore, proof


class BoundedWalTests(unittest.TestCase):
    window = 1 << 20

    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.root = Path(work.name).resolve()
        self.identity = WalIdentity(
            str(uuid4()), "7733091", 1, self.window, self.window
        )
        self.start = self.identity.first_lsn
        self.key = os.urandom(32)
        self.signer = Ed25519PrivateKey.generate()
        self.raw = os.urandom(3 * self.window + 57)
        self.path = self.root / "parts"
        self.path.mkdir()
        self.store = self.open(self.path)
        self.store.initialize()

    def open(self, path):
        return RotatingWal(path, self.identity, self.key, self.window)

    def add_data(self):
        offset = 0
        # Several signed frames straddle part boundaries.
        while offset < len(self.raw):
            chunk = self.raw[offset : offset + 718549]
            challenge = os.urandom(32)
            msg = proof(self.identity, self.start + offset, chunk, challenge)
            self.signer.public_key().verify(
                self.store.accept(self.signer, self.start + offset, chunk, challenge),
                msg,
            )
            offset += len(chunk)

    def assert_content(self, store, wanted):
        observed = sha256()
        cursor = self.start

        def collect(at, raw):
            nonlocal cursor
            self.assertEqual(cursor, at)
            cursor += len(raw)
            observed.update(raw)

        self.assertEqual(store.replay(collect), self.start + len(wanted))
        self.assertEqual(observed.digest(), sha256(wanted).digest())

    def test_crossings_restart_snapshot_and_source_identity(self):
        self.add_data()
        self.assert_content(self.open(self.path), self.raw)
        copied, end = self.store.snapshot(self.root / "offline")
        self.assert_content(copied, self.raw)
        challenge = os.urandom(32)
        self.signer.public_key().verify(
            copied.accept(self.signer, end, b"", challenge),
            proof(self.identity, end, b"", challenge),
        )
        self.store.append(end, b"later bytes")
        self.assert_content(copied, self.raw)
        self.assert_content(self.store, self.raw + b"later bytes")
        self.assertRaisesRegex(
            ValueError, "position", self.store.accept, self.signer, end, b"", challenge
        )

    def test_missing_reordered_or_altered_sealed_file(self):
        self.add_data()
        old = self.store.file(1)
        safe = self.root / "second.sqlite3"
        old.rename(safe)
        self.assertRaisesRegex(ValueError, "inventory", self.store.verified_end)
        shutil.copyfile(self.store.file(0), old)
        self.assertRaisesRegex(
            ValueError, "sealed_wal_changed", self.store.verified_end
        )
        old.unlink()
        safe.rename(old)
        with closing(sqlite3.connect(old)) as db, db:
            db.execute(
                "UPDATE chunks SET cipher=zeroblob(length(cipher)) WHERE start=(SELECT min(start) FROM chunks)"
            )
        self.assertRaisesRegex(
            ValueError,
            "wal_part_snapshot_seal",
            self.store.snapshot,
            self.root / "altered-copy",
        )

    def test_known_active_position_missing_and_false_seal(self):
        self.add_data()
        last = self.store.part(3)
        last.path.unlink()
        last.enroll()
        self.assertRaisesRegex(ValueError, "truncated", self.store.verified_end)
        with closing(sqlite3.connect(self.store.meta)) as db, db:
            db.execute("UPDATE sealed SET tag=zeroblob(32) WHERE idx=0")
        self.assertRaisesRegex(ValueError, "seal_tag", self.store.verified_end)

    def test_interrupted_successor_and_unacknowledged_suffix(self):
        self.store.append(self.start, self.raw[: self.window])
        self.store.part(1).enroll()
        middle = self.start + self.window
        self.assertEqual(self.open(self.path).verified_end(), middle)
        self.store.part(1).append(middle, b"committed on disk")
        self.assert_content(
            self.open(self.path), self.raw[: self.window] + b"committed on disk"
        )

    def test_untracked_successor_with_data_stays_closed(self):
        self.store.append(self.start, self.raw[: self.window])
        next_part = self.store.part(1)
        next_part.enroll()
        next_part.append(self.start + self.window, b"untracked")
        self.assertRaisesRegex(ValueError, "inventory", self.store.verified_end)

    def test_existing_native_archive_window_size_and_key_are_bound(self):
        native = WalStore(self.root / "old.sqlite3", self.identity, self.key)
        native.enroll()
        native.append(self.start, self.raw[:49153])
        target = self.root / "imported"
        target.mkdir()
        migrated = self.open(target)
        migrated.initialize(native)
        self.assert_content(migrated, self.raw[:49153])
        self.assert_content(native, self.raw[:49153])
        self.assertRaisesRegex(
            ValueError,
            "binding",
            RotatingWal(target, self.identity, self.key, 2 * self.window).verified_end,
        )
        self.assertRaisesRegex(
            ValueError,
            "binding",
            RotatingWal(
                target, self.identity, os.urandom(32), self.window
            ).verified_end,
        )

    def test_forward_mirror_refuses_unqualified_cap_and_preserves_old_history(self):
        native = WalStore(self.root / "old.sqlite3", self.identity, self.key)
        native.enroll()
        native.append(self.start, self.raw[:19])
        allow = False
        dual = ForwardReceiver(native, self.store, 2 * self.window, lambda: allow)
        self.assertEqual(dual.synchronize(), self.start + 19)
        cursor = 19
        while cursor < 2 * self.window:
            chunk = self.raw[cursor : min(cursor + self.window, 2 * self.window)]
            dual.accept(self.signer, self.start + cursor, chunk, os.urandom(32))
            cursor += len(chunk)
        at = self.start + cursor
        self.assertRaisesRegex(
            ValueError,
            "qualification_pending",
            dual.accept,
            self.signer,
            at,
            b"!",
            os.urandom(32),
        )
        self.assertEqual(self.store.verified_end(), native.verified_end())
        allow = True
        dual.accept(self.signer, at, b"!", os.urandom(32))
        self.assertEqual(dual.synchronize(), at + 1)
        self.assert_content(native, self.raw[:cursor])
        self.assert_content(self.store, self.raw[:cursor] + b"!")

    def test_both_mirror_crash_directions_and_divergent_same_key(self):
        native = WalStore(self.root / "old.sqlite3", self.identity, self.key)
        native.enroll()
        native.append(self.start, b"old")
        dual = ForwardReceiver(native, self.store, 2 * self.window, lambda: False)
        self.assertEqual(dual.synchronize(), self.start + 3)
        self.store.append(self.start + 3, b"new")
        self.assertEqual(dual.synchronize(), self.start + 6)
        self.assert_content(native, b"oldnew")
        other = WalStore(self.root / "other.sqlite3", self.identity, self.key)
        other.enroll()
        other.append(self.start, b"ong")
        self.assertRaisesRegex(
            ValueError,
            "divergent_independent_wal",
            ForwardReceiver(
                other, self.store, 2 * self.window, lambda: True
            ).synchronize,
        )
