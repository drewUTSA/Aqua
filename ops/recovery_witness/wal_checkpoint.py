"""Gate a signed closure checkpoint on an independently retained physical restore point."""

from contextlib import closing
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat


@dataclass(frozen=True)
class RestorePoint:
    system_id: str
    timeline: int
    sequence: int
    event_digest: str
    record_digest: str
    lsn: int


class RecoverableCheckpoints:
    """Keep an immutable mapping from each witness record to its original database WAL."""

    def __init__(self, path, journal, wal, base_digest, check_base, observe_source):
        self.path = Path(path)
        self.journal = journal
        self.wal = wal
        self.check_base = check_base
        self.observe_source = observe_source
        if (
            self.path.parent.resolve(strict=True) != self.path.parent
            or journal.identity.installation != wal.identity.installation
            or type(base_digest) is not bytes
            or len(base_digest) != 32
        ):
            raise ValueError("wal_checkpoint_identity")
        self.profile = json.dumps(
            [journal.identity.pin(), wal.identity.bytes().hex(), base_digest.hex()],
            separators=(",", ":"),
        ).encode("ascii")
        self.header = hashlib.sha256(self.profile).digest()

    def connect(self):
        st = self.path.lstat()
        if (
            not stat.S_ISREG(st.st_mode)
            or st.st_nlink != 1
            or self.path.resolve(strict=True) != self.path
            or getattr(st, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("wal_checkpoint_path")
        conn = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=3)
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA synchronous=EXTRA")
        if conn.execute("PRAGMA journal_mode").fetchone() != ("delete",):
            conn.close()
            raise ValueError("wal_checkpoint_store_mode")
        return conn

    def enroll(self):
        self.check_base()
        os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
        with closing(self.connect()) as conn, conn:
            conn.execute(
                "CREATE TABLE binding(id INTEGER PRIMARY KEY CHECK(id=1),profile BLOB NOT NULL)"
            )
            conn.execute("INSERT INTO binding VALUES(1,?)", (self.profile,))
            conn.execute(
                "CREATE TABLE cuts(seq INTEGER PRIMARY KEY,digest BLOB NOT NULL UNIQUE,lsn INTEGER NOT NULL,tag BLOB NOT NULL)"
            )

    def tag(self, seq, digest, lsn):
        return hashlib.sha256(
            self.header + seq.to_bytes(8, "big") + digest + lsn.to_bytes(8, "big")
        ).digest()

    def lookup(self, conn, head):
        if conn.execute("SELECT profile FROM binding WHERE id=1").fetchone() != (
            self.profile,
        ):
            raise ValueError("wal_checkpoint_store_profile")
        existing = conn.execute(
            "SELECT digest,lsn,tag FROM cuts WHERE seq=?", (head.sequence,)
        ).fetchone()
        if existing is None:
            return None
        digest, lsn, tag = existing
        if digest != head.record_digest or not hmac.compare_digest(
            tag, self.tag(head.sequence, digest, lsn)
        ):
            raise ValueError("wal_checkpoint_conflict")
        return lsn

    def remember(self, raw, head):
        self.check_base()
        with closing(self.connect()) as conn:
            known = self.lookup(conn, head)
        if known is not None:
            return known
        observed = self.observe_source(raw)
        if (
            type(observed) is not RestorePoint
            or observed.system_id != self.wal.identity.system_id
            or observed.timeline != self.wal.identity.timeline
            or observed.sequence != head.sequence
            or observed.record_digest != head.record_digest.hex()
            or observed.event_digest != head.event_digest.hex()
            or type(observed.lsn) is not int
            or not self.wal.identity.first_lsn
            <= observed.lsn
            <= self.wal.verified_end()
        ):
            raise ValueError("wal_checkpoint_not_retained")
        with closing(self.connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            known = self.lookup(conn, head)
            if known is None:
                previous = conn.execute(
                    "SELECT seq,digest,lsn FROM cuts ORDER BY seq DESC LIMIT 1"
                ).fetchone()
                if previous is None:
                    if head.sequence != 0:
                        raise ValueError("wal_checkpoint_genesis_required")
                elif (head.sequence, head.previous_record) != (
                    previous[0] + 1,
                    previous[1],
                ) or observed.lsn < previous[2]:
                    raise ValueError("wal_checkpoint_lineage")
                conn.execute(
                    "INSERT INTO cuts VALUES(?,?,?,?)",
                    (
                        head.sequence,
                        head.record_digest,
                        observed.lsn,
                        self.tag(head.sequence, head.record_digest, observed.lsn),
                    ),
                )
        with closing(self.connect()) as conn:
            saved = self.lookup(conn, head)
        if saved is None:
            raise ValueError("wal_checkpoint_receipt_missing")
        return saved

    def append(self, generation, raw, *, service_public_key=None):
        # Validate the original authority record before consulting any remote source.
        head = self.journal.identity.checked_record(raw)
        with self.journal._transaction() as conn:
            self.journal._check_service_key(service_public_key)
            if self.journal._state(conn, generation) is not None or conn.execute(
                "SELECT public_key FROM publishers WHERE generation=?", (generation,)
            ).fetchone() != (service_public_key,):
                raise ValueError("wal_checkpoint_publisher_not_current")
            previous = conn.execute(
                "SELECT seq,record FROM records ORDER BY seq DESC LIMIT 1"
            ).fetchone()
            if previous is None:
                raise ValueError("wal_checkpoint_existing_enrollment_required")
            saved = self.journal.identity.checked_record(previous[1])
            if previous[0] != saved.sequence or not (
                (raw == previous[1] and head.sequence == saved.sequence)
                or (
                    head.sequence == saved.sequence + 1
                    and head.previous_record == saved.record_digest
                )
            ):
                raise ValueError("wal_checkpoint_request_not_next")
        lsn = self.remember(raw, head)
        if self.wal.verified_end() < lsn:
            raise ValueError("wal_checkpoint_recovery_bytes_missing")
        self.journal.append(generation, raw, service_public_key=service_public_key)
