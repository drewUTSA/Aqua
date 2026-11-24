"""Durable encrypted PostgreSQL WAL on the installation's independent station."""

from contextlib import closing, contextmanager
from dataclasses import dataclass
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
import struct
from uuid import UUID

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAX_FRAME = 1024 * 1024
DOMAIN = b"Aqua physical WAL archive v1\0"
PROOF = b"Aqua physical WAL independent flush v1\0"


def proof(profile, start, raw, challenge):
    return (
        PROOF
        + hashlib.sha256(profile.bytes()).digest()
        + struct.pack("!QQ", start, start + len(raw))
        + hashlib.sha256(raw).digest()
        + challenge
    )


@dataclass(frozen=True)
class WalIdentity:
    installation: str
    system_id: str
    timeline: int
    segment_bytes: int
    first_lsn: int

    def bytes(self):
        if (
            str(UUID(self.installation)) != self.installation
            or not re.fullmatch(r"[1-9][0-9]{0,19}", self.system_id)
            or int(self.system_id) >= 2**64
            or type(self.timeline) is not int
            or not 1 <= self.timeline < 2**32
            or self.segment_bytes not in [2**bit for bit in range(20, 31)]
            or type(self.first_lsn) is not int
            or not 0 < self.first_lsn < 2**63
            or self.first_lsn % self.segment_bytes
        ):
            raise ValueError("wal_archive_identity")
        return json.dumps(
            [
                self.installation,
                self.system_id,
                self.timeline,
                self.segment_bytes,
                self.first_lsn,
            ],
            separators=(",", ":"),
        ).encode("ascii")


class WalStore:
    def __init__(self, path: Path, identity: WalIdentity, key: bytes):
        self.path = Path(path)
        self.identity = identity
        if self.path.parent.resolve(strict=True) != self.path.parent or len(key) != 32:
            raise ValueError("wal_archive_directory_or_key")
        self.profile = identity.bytes()
        self.header = hashlib.sha256(DOMAIN + self.profile).digest()
        self.aead = AESGCM(key)

    def file_id(self):
        meta = self.path.lstat()
        if (
            not stat.S_ISREG(meta.st_mode)
            or meta.st_nlink != 1
            or self.path.resolve(strict=True) != self.path
            or getattr(meta, "st_file_attributes", 0)
            & stat.FILE_ATTRIBUTE_REPARSE_POINT
        ):
            raise ValueError("wal_archive_path")
        return meta.st_dev, meta.st_ino

    @contextmanager
    def transaction(self, *, initialize=False):
        inode = self.file_id()
        with closing(
            sqlite3.connect(
                self.path.as_uri() + "?mode=rw",
                uri=True,
                timeout=3,
                isolation_level=None,
            )
        ) as conn:
            conn.execute("PRAGMA trusted_schema=OFF")
            conn.execute("PRAGMA synchronous=EXTRA")
            if conn.execute("PRAGMA journal_mode").fetchone() != ("delete",):
                raise ValueError("wal_archive_sqlite_mode")
            conn.execute("BEGIN IMMEDIATE")
            try:
                if not initialize:
                    value = conn.execute(
                        "SELECT identity,key_proof FROM profile WHERE singleton=1"
                    ).fetchone()
                    if not value or value[0] != self.profile or len(value[1]) != 28:
                        raise ValueError("wal_archive_profile")
                    self.aead.decrypt(value[1][:12], value[1][12:], self.header)
                yield conn
                if self.file_id() != inode:
                    raise ValueError("wal_archive_replaced")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        if self.file_id() != inode:
            raise ValueError("wal_archive_replaced")

    def enroll(self):
        os.close(os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600))
        with self.transaction(initialize=True) as conn:
            conn.execute(
                "CREATE TABLE profile(singleton INTEGER PRIMARY KEY CHECK(singleton=1),identity BLOB NOT NULL,key_proof BLOB NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE chunks(start INTEGER PRIMARY KEY,finish INTEGER NOT NULL UNIQUE,nonce BLOB NOT NULL UNIQUE,cipher BLOB NOT NULL,previous BLOB NOT NULL,digest BLOB NOT NULL UNIQUE)"
            )
            conn.execute(
                "CREATE TABLE tail(singleton INTEGER PRIMARY KEY CHECK(singleton=1),pos INTEGER NOT NULL,digest BLOB NOT NULL)"
            )
            nonce = os.urandom(12)
            conn.execute(
                "INSERT INTO profile VALUES(1,?,?)",
                (self.profile, nonce + self.aead.encrypt(nonce, b"", self.header)),
            )
            conn.execute(
                "INSERT INTO tail VALUES(1,?,?)", (self.identity.first_lsn, self.header)
            )

    def open_chunk(self, row, previous):
        start, finish, nonce, cipher, last, digest = row
        if (
            not 0 < finish - start <= MAX_FRAME
            or len(cipher) != finish - start + 16
            or last != previous
        ):
            raise ValueError("wal_archive_gap_or_length")
        aad = self.header + struct.pack("!QQ", start, finish) + previous
        if not hmac.compare_digest(
            hashlib.sha256(aad + nonce + cipher).digest(), digest
        ):
            raise ValueError("wal_archive_digest")
        return self.aead.decrypt(nonce, cipher, aad)

    def head(self, conn):
        tail = conn.execute("SELECT pos,digest FROM tail WHERE singleton=1").fetchone()
        row = conn.execute(
            "SELECT * FROM chunks ORDER BY start DESC LIMIT 1"
        ).fetchone()
        if row is None:
            if tail != (self.identity.first_lsn, self.header):
                raise ValueError("wal_archive_empty_tail")
        else:
            if tail != (row[1], row[5]):
                raise ValueError("wal_archive_tail")
            self.open_chunk(row, row[4])
        return tail

    def append(self, start, raw):
        if (
            type(raw) is not bytes
            or not 0 < len(raw) <= MAX_FRAME
            or type(start) is not int
            or not 0 < start < 2**63 - len(raw)
        ):
            raise ValueError("wal_archive_input")
        finish = start + len(raw)
        with self.transaction() as conn:
            pos, previous = self.head(conn)
            if start != pos:
                raise ValueError("wal_archive_position")
            aad = self.header + struct.pack("!QQ", start, finish) + previous
            nonce = os.urandom(12)
            cipher = self.aead.encrypt(nonce, raw, aad)
            digest = hashlib.sha256(aad + nonce + cipher).digest()
            conn.execute(
                "INSERT INTO chunks VALUES(?,?,?,?,?,?)",
                (start, finish, nonce, cipher, previous, digest),
            )
            conn.execute(
                "UPDATE tail SET pos=?,digest=? WHERE singleton=1", (finish, digest)
            )
        # Do not acknowledge a sender merely because the INSERT completed.
        with self.transaction() as conn:
            if self.head(conn) != (finish, digest):
                raise ValueError("wal_archive_durable_readback")
        return finish

    def verified_end(self):
        return self.replay(lambda position, raw: None)

    def accept(self, signing_key, start, raw, challenge):
        if len(challenge) != 32:
            raise ValueError("wal_archive_challenge")
        if raw:
            self.append(start, raw)
        elif start != self.verified_end():
            raise ValueError("wal_archive_reconnect_position")
        return signing_key.sign(proof(self.identity, start, raw, challenge))

    def replay(self, sink):
        """Verify every byte offered to restore within one consistent archive transaction."""
        with self.transaction() as conn:
            pos, previous = self.identity.first_lsn, self.header
            for row in conn.execute("SELECT * FROM chunks ORDER BY start"):
                if row[0] != pos:
                    raise ValueError("wal_archive_replay_gap")
                raw = self.open_chunk(row, previous)
                sink(pos, raw)
                pos, previous = row[1], row[5]
            if self.head(conn) != (pos, previous):
                raise ValueError("wal_archive_final_tail")
            return pos
