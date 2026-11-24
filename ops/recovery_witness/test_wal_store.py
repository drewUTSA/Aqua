import os
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest

from cryptography.exceptions import InvalidSignature, InvalidTag
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .wal_store import WalIdentity, WalStore, proof


class EncryptedWalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.key = os.urandom(32)
        self.signer = Ed25519PrivateKey.generate()
        self.identity = WalIdentity(
            "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
            "7412345678901234567",
            1,
            16 << 20,
            32 << 20,
        )
        self.path = Path(self.temp.name) / "blocks.sqlite"
        self.store = WalStore(self.path, self.identity, self.key)
        self.store.enroll()
        self.start = self.identity.first_lsn

    def test_flush_after_reopen_and_challenge_bound_to_bytes(self):
        raw = b"This is a fictional, recoverable database page marker."
        challenge = os.urandom(32)
        receipt = self.store.accept(self.signer, self.start, raw, challenge)
        self.signer.public_key().verify(
            receipt, proof(self.identity, self.start, raw, challenge)
        )
        with self.assertRaises(InvalidSignature):
            self.signer.public_key().verify(
                receipt, proof(self.identity, self.start, raw + b"x", challenge)
            )
        with self.assertRaises(InvalidSignature):
            self.signer.public_key().verify(
                receipt, proof(self.identity, self.start, raw, os.urandom(32))
            )
        self.assertNotIn(raw, self.path.read_bytes())
        fresh = WalStore(self.path, self.identity, self.key)
        position = self.start + len(raw)
        self.assertEqual(fresh.verified_end(), position)
        self.assertEqual(len(fresh.accept(self.signer, position, b"", challenge)), 64)
        self.assertRaises(
            ValueError, fresh.accept, self.signer, self.start, b"", challenge
        )
        reconstructed = []
        self.assertEqual(
            fresh.replay(lambda start, data: reconstructed.append((start, data))),
            position,
        )
        self.assertEqual(reconstructed, [(self.start, raw)])

    def test_wrong_key_identity_gap_and_duplicate_never_confirm(self):
        self.store.append(self.start, b"first")
        self.assertRaises(ValueError, self.store.append, self.start, b"fork")
        self.assertRaises(ValueError, self.store.append, self.start + 6, b"gap")
        self.assertRaises(
            InvalidTag, WalStore(self.path, self.identity, os.urandom(32)).verified_end
        )
        wrong = WalIdentity(
            self.identity.installation,
            self.identity.system_id,
            2,
            self.identity.segment_bytes,
            self.start,
        )
        self.assertRaises(ValueError, WalStore(self.path, wrong, self.key).verified_end)
        self.assertRaises(FileExistsError, self.store.enroll)

    def test_modification_and_missing_intermediate_bytes_fail_replay(self):
        self.store.append(self.start, b"first")
        self.store.append(self.start + 5, b"second")
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                "UPDATE chunks SET cipher=zeroblob(length(cipher)) WHERE start=?",
                (self.start,),
            )
        self.assertRaises(ValueError, self.store.replay, lambda pos, data: None)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DELETE FROM chunks WHERE start=?", (self.start,))
        self.assertRaises(ValueError, self.store.replay, lambda pos, data: None)

    def test_missing_and_replaced_paths_require_renewed_custody(self):
        self.path.unlink()
        self.assertRaises(FileNotFoundError, self.store.verified_end)
        self.assertFalse(self.path.exists())


if __name__ == "__main__":
    unittest.main()
