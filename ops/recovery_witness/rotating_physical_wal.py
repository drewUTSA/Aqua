"""Bounded encrypted WAL files for one original PostgreSQL timeline and publication identity."""

from contextlib import closing, contextmanager
from dataclasses import replace
from hashlib import file_digest
import hmac
import os
from pathlib import Path
import shutil
import sqlite3
import stat
import struct

if __package__:
    from .wal_store import MAX_FRAME, WalStore, proof
else:
    from wal_store import MAX_FRAME, WalStore, proof


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def exact_file(path):
    info = path.lstat()
    require(
        path.resolve(strict=True) == path
        and stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and not getattr(info, "st_file_attributes", 0)
        & stat.FILE_ATTRIBUTE_REPARSE_POINT,
        "wal_part_path",
    )
    return info.st_dev, info.st_ino


def digest(path):
    with path.open("rb") as stream:
        return file_digest(stream, "sha256").digest()


class RotatingWal:
    """The active file and all sealed files stay on the independent recovery station.

    A single SQLite metadata writer serializes appends, seals, snapshots and every
    acknowledgement. An interrupted append may leave an unacknowledged durable
    suffix, which is authenticated and adopted before a reconnect can report it.
    No file is removed by this implementation.
    """

    def __init__(self, directory, identity, key, window):
        self.path = Path(directory)
        require(
            self.path.resolve(strict=True) == self.path and self.path.is_dir(),
            "wal_part_directory",
        )
        require(
            type(window) is int
            and identity.segment_bytes <= window <= 2 * 1024**3
            and window % identity.segment_bytes == 0
            and len(key) == 32,
            "wal_part_window",
        )
        self.identity = identity
        self.key = key
        self.window = window
        self.meta = self.path / "parts.sqlite3"
        self.profile = identity.bytes() + struct.pack("!Q", window)
        self.auth = hmac.digest(
            key, b"Aqua bounded WAL catalog v1\0" + self.profile, "sha256"
        )
        self.first = identity.first_lsn

    def tag(self, purpose, *values):
        return hmac.digest(
            self.auth,
            purpose + b"\0" + b"".join(struct.pack("!I", len(v)) + v for v in values),
            "sha256",
        )

    def file(self, idx):
        require(type(idx) is int and 0 <= idx <= 65535, "wal_part_index")
        return self.path / f"wal-{idx:05d}.sqlite3"

    def part(self, idx):
        return WalStore(
            self.file(idx),
            replace(self.identity, first_lsn=self.first + idx * self.window),
            self.key,
        )

    @contextmanager
    def catalog(self, initial=False):
        original = exact_file(self.meta)
        with closing(
            sqlite3.connect(
                self.meta.as_uri() + "?mode=rw",
                uri=True,
                timeout=8,
                isolation_level=None,
            )
        ) as db:
            db.execute("PRAGMA trusted_schema=OFF")
            db.execute("PRAGMA synchronous=EXTRA")
            require(
                db.execute("PRAGMA journal_mode").fetchone() == ("delete",),
                "wal_part_catalog_mode",
            )
            db.execute("BEGIN IMMEDIATE")
            try:
                if not initial:
                    row = db.execute(
                        "SELECT profile,tag FROM installation WHERE id=1"
                    ).fetchone()
                    require(
                        row is not None
                        and row[0] == self.profile
                        and hmac.compare_digest(
                            row[1], self.tag(b"identity", self.profile)
                        ),
                        "wal_part_binding",
                    )
                yield db
                require(exact_file(self.meta) == original, "wal_part_catalog_replaced")
                db.commit()
            except BaseException:
                db.rollback()
                raise

    def initialize(self, existing=None):
        require(not any(self.path.iterdir()), "wal_part_directory_nonempty")
        with self.meta.open("xb"):
            pass
        with self.catalog(initial=True) as db:
            db.executescript(
                "CREATE TABLE installation(id INTEGER PRIMARY KEY CHECK(id=1),profile BLOB NOT NULL,tag BLOB NOT NULL);"
                "CREATE TABLE sealed(idx INTEGER PRIMARY KEY,end_lsn INTEGER NOT NULL,digest BLOB NOT NULL,tag BLOB NOT NULL);"
                "CREATE TABLE progress(id INTEGER PRIMARY KEY CHECK(id=1),idx INTEGER NOT NULL,lsn INTEGER NOT NULL,tag BLOB NOT NULL);"
            )
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "INSERT INTO installation VALUES(1,?,?)",
                (self.profile, self.tag(b"identity", self.profile)),
            )
            if existing is None:
                self.part(0).enroll()
            else:
                require(
                    self.part(0).identity == existing.identity
                    and existing.path.resolve(strict=True) == existing.path,
                    "wal_part_import_source",
                )
                self.sqlite_copy(existing.path, self.file(0))
            end = self.part(0).verified_end()
            require(
                self.first <= end <= self.first + self.window,
                "original_wal_exceeds_first_part",
            )
            self.save(db, 0, end)

    @staticmethod
    def sqlite_copy(source, target):
        exact_file(source)
        with target.open("xb"):
            pass
        with (
            closing(
                sqlite3.connect(source.as_uri() + "?mode=ro", uri=True, timeout=8)
            ) as src,
            closing(sqlite3.connect(target)) as dst,
        ):
            src.backup(dst, pages=256, sleep=0.02)
            require(
                dst.execute("PRAGMA quick_check").fetchall() == [("ok",)],
                "wal_part_snapshot_integrity",
            )
        with target.open("rb+") as out:
            os.fsync(out.fileno())

    def save(self, db, idx, end):
        current = struct.pack("!QQ", idx, end)
        db.execute(
            "INSERT OR REPLACE INTO progress VALUES(1,?,?,?)",
            (idx, end, self.tag(b"progress", current)),
        )

    def active(self, db):
        state = db.execute("SELECT idx,lsn,tag FROM progress WHERE id=1").fetchone()
        require(state is not None, "wal_part_progress")
        idx, pos, tag = state
        require(
            0 <= idx <= 65535
            and self.first + idx * self.window
            <= pos
            <= self.first + (idx + 1) * self.window
            and hmac.compare_digest(
                tag, self.tag(b"progress", struct.pack("!QQ", idx, pos))
            ),
            "wal_part_progress_authentication",
        )
        return idx, pos

    def seals(self, db, active):
        rows = db.execute(
            "SELECT idx,end_lsn,digest,tag FROM sealed ORDER BY idx"
        ).fetchall()
        require(len(rows) == active, "wal_part_missing_seal")
        previous = self.tag(b"genesis")
        for i, (idx, end, hashed, tag) in enumerate(rows):
            require(
                idx == i
                and end == self.first + (idx + 1) * self.window
                and len(hashed) == 32,
                "wal_part_continuity",
            )
            expected = self.tag(b"seal", previous, struct.pack("!QQ", idx, end), hashed)
            require(hmac.compare_digest(expected, tag), "wal_part_seal_tag")
            previous = tag
        return rows, previous

    def replay_at(self, db, sink):
        idx, watermark = self.active(db)
        sealed, _ = self.seals(db, idx)
        names = {p.name for p in self.path.glob("wal-*.sqlite3")}
        expected_names = {self.file(i).name for i in range(idx + 1)}
        if names != expected_names:
            # The successor's native database can be created just before the
            # metadata transaction commits. Adopt exactly one verified empty
            # successor, only after proving its predecessor is full.
            require(
                idx < 65535
                and names == expected_names | {self.file(idx + 1).name}
                and self.part(idx + 1).verified_end()
                == self.first + (idx + 1) * self.window,
                "wal_part_file_inventory",
            )
            self.roll(db, idx)
            return self.replay_at(db, sink)
        for i, end, expected, _ in sealed:
            p = self.part(i)
            require(
                digest(p.path) == expected and p.replay(sink) == end,
                "sealed_wal_changed",
            )
        end = self.part(idx).replay(sink)
        require(
            watermark <= end <= self.first + (idx + 1) * self.window,
            "wal_part_truncated_or_overlong",
        )
        if end > watermark:
            self.save(db, idx, end)
        return end

    def replay(self, sink):
        with self.catalog() as db:
            return self.replay_at(db, sink)

    def verified_end(self):
        return self.replay(lambda pos, raw: None)

    def snapshot(self, target):
        """Capture an independently verifiable bounded-file chain while appends continue."""
        target = Path(target)
        require(
            target.parent.resolve(strict=True) == target.parent and not target.exists(),
            "wal_part_snapshot_target",
        )
        # The catalog's read snapshot selects a contiguous history. Sealed
        # files are immutable by protocol. The previous active file may gain a
        # genuine contiguous suffix or become sealed during copying. Either
        # state passes independent replay only when it covers this catalog cut.
        target.mkdir()
        require(target.resolve(strict=True) == target, "wal_part_snapshot_path")
        snap = RotatingWal(target, self.identity, self.key, self.window)
        self.sqlite_copy(self.meta, snap.meta)
        with snap.catalog() as db:
            active, floor = snap.active(db)
            rows, _ = snap.seals(db, active)
        expected = sum(self.file(i).stat().st_size for i in range(active + 1))
        require(
            shutil.disk_usage(target).free > expected + 128 * 1024**2,
            "wal_part_snapshot_space",
        )
        for idx, _, hashed, _ in rows:
            src = self.file(idx)
            identity = exact_file(src)
            with src.open("rb") as inp, snap.file(idx).open("xb") as out:
                shutil.copyfileobj(inp, out)
                out.flush()
                os.fsync(out.fileno())
            require(
                exact_file(src) == identity and digest(snap.file(idx)) == hashed,
                "wal_part_snapshot_seal",
            )
        self.sqlite_copy(self.file(active), snap.file(active))
        end = snap.verified_end()
        require(end >= floor, "wal_part_snapshot_behind")
        return snap, end

    def roll(self, db, idx):
        old = self.part(idx)
        end = self.first + (idx + 1) * self.window
        require(old.verified_end() == end, "unfinished_wal_part")
        _, previous = self.seals(db, idx)
        hashed = digest(old.path)
        entry = self.tag(b"seal", previous, struct.pack("!QQ", idx, end), hashed)
        # Recover a create-only, fully authenticated empty successor left by a
        # power loss before the catalog COMMIT. A populated orphan stays closed.
        new = self.part(idx + 1)
        if new.path.exists():
            require(new.verified_end() == end, "untracked_nonempty_wal_part")
        else:
            new.enroll()
        db.execute("INSERT INTO sealed VALUES(?,?,?,?)", (idx, end, hashed, entry))
        self.save(db, idx + 1, end)
        return idx + 1

    def append(self, pos, raw):
        require(
            type(raw) is bytes and 0 < len(raw) <= MAX_FRAME and type(pos) is int,
            "wal_part_frame",
        )
        offset = 0
        while offset < len(raw):
            # Separate durable commits make an exact native boundary resumable.
            with self.catalog() as db:
                idx, lower = self.active(db)
                part = self.part(idx)
                with part.transaction() as conn:
                    durable = part.head(conn)[0]
                require(lower <= durable == pos + offset, "wal_part_write_position")
                end = self.first + (idx + 1) * self.window
                if durable == end:
                    self.roll(db, idx)
                    continue
                count = min(len(raw) - offset, end - durable)
                require(
                    shutil.disk_usage(self.path).free
                    >= max(128 * 1024**2, 4 * MAX_FRAME),
                    "wal_part_free_space",
                )
                finish = part.append(durable, raw[offset : offset + count])
                self.save(db, idx, finish)
                offset += count
        return pos + len(raw)

    def accept(self, signer, start, raw, challenge):
        require(type(challenge) is bytes and len(challenge) == 32, "wal_part_challenge")
        if raw:
            self.append(start, raw)
        else:
            require(start == self.verified_end(), "wal_part_reconnect_position")
        return signer.sign(proof(self.identity, start, raw, challenge))
