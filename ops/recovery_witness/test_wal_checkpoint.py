from contextlib import closing
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from retirement import checkpoint

from .journal import Identity, Witness
from .wal_checkpoint import RecoverableCheckpoints, RestorePoint
from .wal_store import WalIdentity, WalStore


class RecoverableCheckpointTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        folder = Path(tmp.name)
        self.private = Ed25519PrivateKey.generate()
        self.publisher = Ed25519PrivateKey.generate().public_key().public_bytes_raw()
        self.identity = Identity(
            str(uuid4()),
            str(uuid4()),
            os.urandom(32),
            self.private.public_key().public_bytes_raw(),
        )
        self.journal = Witness(folder / "journal.sqlite3", self.identity)
        self.genesis = self.signed(0, bytes(32))
        self.journal.enroll(self.genesis, service_public_key=self.publisher)
        identity = WalIdentity(
            self.identity.installation, "137192837465", 1, 1 << 24, 1 << 24
        )
        self.store = WalStore(folder / "archive.sqlite3", identity, os.urandom(32))
        self.store.enroll()
        self.gate = RecoverableCheckpoints(
            folder / "cuts.sqlite3",
            self.journal,
            self.store,
            bytes(32),
            lambda: None,
            self.observe,
        )
        self.gate.enroll()
        self.calls = 0
        self.end = self.store.verified_end()

    def signed(self, seq, previous):
        body = checkpoint.payload(
            self.identity.installation,
            self.identity.key_id,
            seq,
            bytes(32) if seq == 0 else hashlib.sha256(str(seq).encode()).digest(),
            previous,
            self.identity.commitment,
        )
        return body + self.private.sign(checkpoint.DOMAIN + body)

    def observe(self, raw):
        self.calls += 1
        head = self.identity.checked_record(raw)
        return RestorePoint(
            self.store.identity.system_id,
            1,
            head.sequence,
            head.event_digest.hex(),
            head.record_digest.hex(),
            self.end,
        )

    def offer(self, raw):
        return self.gate.append(1, raw, service_public_key=self.publisher)

    def test_new_closure_requires_original_wal_and_idempotent_readback(self):
        self.offer(self.genesis)
        self.end += 5
        second = self.signed(1, hashlib.sha256(self.genesis).digest())
        with self.assertRaisesRegex(ValueError, "not_retained"):
            self.offer(second)
        self.store.append(self.end - 5, b"fresh")
        self.offer(second)
        self.assertEqual(self.calls, 3)
        self.offer(second)
        self.assertEqual(self.calls, 3)
        with closing(self.gate.connect()) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM cuts").fetchone(), (2,))
        self.store.path.unlink()
        with self.assertRaises(FileNotFoundError):
            self.offer(second)

    def test_other_cluster_or_fork_never_enters_station_state(self):
        self.gate.observe_source = lambda raw: replace(self.observe(raw), timeline=2)
        with self.assertRaisesRegex(ValueError, "not_retained"):
            self.offer(self.genesis)
        self.gate.observe_source = self.observe
        self.offer(self.genesis)
        with self.assertRaisesRegex(ValueError, "not_next"):
            self.offer(self.signed(1, bytes(32)))
        self.assertEqual(self.calls, 2)
        with closing(self.gate.connect()) as con:
            self.assertEqual(con.execute("SELECT count(*) FROM cuts").fetchone(), (1,))

    def test_inaccessible_base_fenced_generation_and_invalid_signature(self):
        self.journal.fence(1, str(uuid4()))
        with self.assertRaisesRegex(ValueError, "not_current"):
            self.offer(self.genesis)
        self.assertEqual(self.calls, 0)
        broken = bytearray(self.genesis)
        broken[110] ^= 1
        with self.assertRaises(checkpoint.CheckpointUnavailable):
            self.offer(bytes(broken))
        self.gate.check_base = lambda: (_ for _ in ()).throw(ValueError("missing_base"))
        with self.assertRaisesRegex(ValueError, "missing_base"):
            self.gate.remember(self.genesis, self.identity.checked_record(self.genesis))

    def test_missing_older_cut_requires_handled_recovery(self):
        self.journal.append(
            1,
            self.signed(1, hashlib.sha256(self.genesis).digest()),
            service_public_key=self.publisher,
        )
        with self.assertRaisesRegex(ValueError, "genesis_required"):
            self.offer(self.signed(1, hashlib.sha256(self.genesis).digest()))
