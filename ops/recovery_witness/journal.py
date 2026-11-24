"""Signed retirement checkpoints kept by the independent recovery computer."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat

from retirement.checkpoint import RECORD_BYTES, ZERO, decode
from retirement.fingerprints import canonical_uuid


class WitnessUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class Identity:
    installation: str
    key_id: str
    commitment: bytes
    public_key: bytes

    def __post_init__(self):
        canonical_uuid(self.installation)
        canonical_uuid(self.key_id)
        if any(
            type(value) is not bytes or len(value) != 32
            for value in (self.commitment, self.public_key)
        ):
            raise WitnessUnavailable("checkpoint_witness_invalid_identity")

    def checked_record(self, raw):
        return decode(
            raw,
            self.public_key,
            installation=self.installation,
            key_id=self.key_id,
            commitment=self.commitment,
        )

    def pin(self):
        return json.dumps(
            [
                self.installation,
                self.key_id,
                self.commitment.hex(),
                self.public_key.hex(),
            ],
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class FrozenHead:
    generation: int
    fence_id: str
    sequence: int
    head: bytes
    chain_sha256: str


class Witness:
    """One journal per installation, on storage independent of the publisher.

    Provision its directory and channel permissions before enrollment. The
    enrollment identity comes from the installation ceremony. Archive metadata
    cannot select the identity, file, generation or recovery fence.
    """

    def __init__(self, path: Path, identity: Identity):
        self.path = Path(path)
        if (
            not self.path.is_absolute()
            or self.path.parent.resolve(strict=True) != self.path.parent
        ):
            raise WitnessUnavailable("checkpoint_witness_directory")
        self.identity = identity

    def _file_id(self):
        meta = self.path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_nlink != 1
            or self.path.resolve(strict=True) != self.path
            or getattr(meta, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise WitnessUnavailable("checkpoint_witness_file")
        return meta.st_dev, meta.st_ino

    @contextmanager
    def _transaction(self):
        # mode=rw prevents a missing witness from silently becoming an empty DB.
        before = self._file_id()
        with closing(
            sqlite3.connect(
                self.path.as_uri() + "?mode=rw",
                uri=True,
                timeout=2,
                isolation_level=None,
            )
        ) as conn:
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("PRAGMA synchronous=EXTRA")
            if conn.execute("PRAGMA journal_mode").fetchone() != ("delete",):
                raise WitnessUnavailable("checkpoint_witness_journal_mode")
            conn.execute("BEGIN IMMEDIATE")
            try:
                yield conn
                if self._file_id() != before:
                    raise WitnessUnavailable("checkpoint_witness_replaced")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        if self._file_id() != before:
            raise WitnessUnavailable("checkpoint_witness_replaced")

    def enroll(self, genesis: bytes, *, service_public_key=None):
        head = self.identity.checked_record(genesis)
        if head.sequence != 0 or head.previous_record != ZERO:
            raise WitnessUnavailable("checkpoint_witness_requires_genesis")
        self._check_service_key(service_public_key)
        if service_public_key == self.identity.public_key:
            raise WitnessUnavailable("checkpoint_witness_separate_service_key")
        # A crashed enrollment is inspected as an incomplete file. Neither
        # this path nor ordinary reads can truncate, replace or re-enroll it.
        fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(fd)
        with self._transaction() as conn:
            conn.execute(
                "CREATE TABLE state (singleton INTEGER PRIMARY KEY CHECK(singleton = 1), "
                "identity TEXT NOT NULL, generation INTEGER NOT NULL, fence TEXT)"
            )
            conn.execute(
                "CREATE TABLE records (seq INTEGER PRIMARY KEY, record BLOB NOT NULL "
                f"CHECK(length(record) = {RECORD_BYTES}))"
            )
            conn.execute(
                "CREATE TABLE publishers (generation INTEGER PRIMARY KEY, public_key BLOB UNIQUE)"
            )
            conn.execute("INSERT INTO publishers VALUES (1, ?)", (service_public_key,))
            conn.execute(
                "INSERT INTO state VALUES (1, ?, 1, NULL)", (self.identity.pin(),)
            )
            conn.execute(
                "CREATE TABLE tail (singleton INTEGER PRIMARY KEY CHECK(singleton=1), seq INTEGER NOT NULL, digest BLOB NOT NULL)"
            )
            conn.execute("INSERT INTO tail VALUES (1, 0, ?)", (head.record_digest,))
            conn.execute("INSERT INTO records VALUES (0, ?)", (genesis,))
        return head.record_digest

    def _state(self, conn, generation):
        if type(generation) is not int or not 0 < generation < 2**63 - 1:
            raise WitnessUnavailable("checkpoint_witness_generation")
        row = conn.execute(
            "SELECT identity, generation, fence FROM state WHERE singleton=1"
        ).fetchone()
        if row is None or row[:2] != (self.identity.pin(), generation):
            raise WitnessUnavailable("checkpoint_witness_generation_or_identity")
        return row[2]

    @staticmethod
    def _check_service_key(value):
        if value is not None and (type(value) is not bytes or len(value) != 32):
            raise WitnessUnavailable("checkpoint_witness_service_key")

    def append(self, generation: int, raw: bytes, *, service_public_key=None):
        """Commit and flush one next record before returning its acknowledgement."""
        proposed = self.identity.checked_record(raw)
        with self._transaction() as conn:
            if self._state(conn, generation) is not None:
                raise WitnessUnavailable("checkpoint_witness_fenced")
            self._check_service_key(service_public_key)
            if conn.execute(
                "SELECT public_key FROM publishers WHERE generation=?", (generation,)
            ).fetchone() != (service_public_key,):
                raise WitnessUnavailable("checkpoint_witness_publisher_identity")
            last = conn.execute(
                "SELECT seq, record FROM records ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if last is None:
                raise WitnessUnavailable("checkpoint_witness_empty")
            saved = self.identity.checked_record(last[1])
            if saved.sequence != last[0] or conn.execute(
                "SELECT seq,digest FROM tail WHERE singleton=1"
            ).fetchone() != (saved.sequence, saved.record_digest):
                raise WitnessUnavailable("checkpoint_witness_stored_sequence")
            if proposed.sequence == saved.sequence and raw == last[1]:
                pass  # The prior response may have been lost after durable commit.
            elif (
                proposed.sequence == saved.sequence + 1
                and proposed.previous_record == saved.record_digest
            ):
                conn.execute(
                    "INSERT INTO records VALUES (?, ?)", (proposed.sequence, raw)
                )
                conn.execute(
                    "UPDATE tail SET seq=?,digest=? WHERE singleton=1",
                    (proposed.sequence, proposed.record_digest),
                )
            else:
                raise WitnessUnavailable("checkpoint_witness_stale_gap_or_fork")
        return proposed.record_digest

    def _scan(self, conn, generation, fence_id):
        digest = hashlib.sha256()
        previous = ZERO
        head = None
        raw = b""
        for expected, (seq, raw) in enumerate(
            conn.execute("SELECT seq, record FROM records ORDER BY seq")
        ):
            head = self.identity.checked_record(raw)
            if (
                seq != expected
                or head.sequence != seq
                or head.previous_record != previous
            ):
                raise WitnessUnavailable("checkpoint_witness_broken_chain")
            digest.update(raw)
            previous = head.record_digest
        if head is None or conn.execute(
            "SELECT seq,digest FROM tail WHERE singleton=1"
        ).fetchone() != (head.sequence, head.record_digest):
            raise WitnessUnavailable("checkpoint_witness_empty")
        return FrozenHead(generation, fence_id, head.sequence, raw, digest.hexdigest())

    def fence(self, generation: int, fence_id: str):
        """Serialize the recovery cut with every publication, including retries."""
        canonical_uuid(fence_id)
        with self._transaction() as conn:
            current_fence = self._state(conn, generation)
            if current_fence not in (None, fence_id):
                raise WitnessUnavailable("checkpoint_witness_different_fence")
            conn.execute("UPDATE state SET fence=? WHERE singleton=1", (fence_id,))
        # Close publication durably first. Even a corrupt history or interrupted
        # scan must leave this generation fenced for the owner's investigation.
        return self.frozen_head(generation, fence_id)

    def frozen_head(self, generation: int, fence_id: str):
        """Read the current fence from the independent store on every recovery."""
        canonical_uuid(fence_id)
        with self._transaction() as conn:
            if self._state(conn, generation) != fence_id:
                raise WitnessUnavailable("checkpoint_witness_fence_mismatch")
            return self._scan(conn, generation, fence_id)

    @contextmanager
    def recovery_cut(self, generation: int, fence_id: str, restored_chain: bytes):
        """Keep the independent cut fixed while the offline recovery runs.

        Neither a release nor a publication can commit during this transaction.
        If the callback fails or this process exits, the previous committed
        fence survives. This operation never reopens writers.
        """
        canonical_uuid(fence_id)
        with self._transaction() as conn:
            if self._state(conn, generation) != fence_id:
                raise WitnessUnavailable("checkpoint_witness_fence_mismatch")
            cut = self._scan(conn, generation, fence_id)
            if (
                type(restored_chain) is not bytes
                or len(restored_chain) != (cut.sequence + 1) * RECORD_BYTES
                or hashlib.sha256(restored_chain).hexdigest() != cut.chain_sha256
                or restored_chain[-RECORD_BYTES:] != cut.head
            ):
                raise WitnessUnavailable("checkpoint_witness_restore_does_not_match")
            yield cut

    def release(self, cut: FrozenHead, *, new_service_public_key=None):
        """Owner-only after external restore validation and old-writer fencing.

        New-generation publishing must use its separately authorized channel.
        The old generation remains closed across all future reopenings.
        """
        canonical_uuid(cut.fence_id)
        with self._transaction() as conn:
            if self._state(conn, cut.generation) != cut.fence_id:
                raise WitnessUnavailable("checkpoint_witness_fence_mismatch")
            if self._scan(conn, cut.generation, cut.fence_id) != cut:
                raise WitnessUnavailable("checkpoint_witness_fence_changed")
            self._check_service_key(new_service_public_key)
            if new_service_public_key == self.identity.public_key:
                raise WitnessUnavailable("checkpoint_witness_separate_service_key")
            old = conn.execute(
                "SELECT public_key FROM publishers WHERE generation=?",
                (cut.generation,),
            ).fetchone()
            if old is None or old[0] is not None and new_service_public_key is None:
                raise WitnessUnavailable("checkpoint_witness_new_publisher_required")
            # A previously assigned service credential cannot acquire a later generation.
            conn.execute(
                "INSERT INTO publishers VALUES (?, ?)",
                (cut.generation + 1, new_service_public_key),
            )
            conn.execute(
                "UPDATE state SET generation=generation+1, fence=NULL WHERE singleton=1"
            )
        return cut.generation + 1
