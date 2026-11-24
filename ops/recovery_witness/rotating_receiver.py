"""Maintain both original and bounded encrypted custody during forward migration."""

from hashlib import sha256

if __package__:
    from .wal_store import MAX_FRAME, proof
    from .rotating_physical_wal import require
else:
    from wal_store import MAX_FRAME, proof
    from rotating_physical_wal import require


def copy_range(source, target, start, end):
    """Coalesce verified native input into bounded frames during offline catch-up."""
    cursor = start
    buf = bytearray()

    def flush():
        nonlocal cursor
        if buf:
            target.append(cursor, bytes(buf))
            cursor += len(buf)
            buf.clear()

    def collect(pos, raw):
        lo = max(start, pos)
        hi = min(end, pos + len(raw))
        if hi <= lo:
            return
        require(lo == cursor + len(buf), "catchup_wal_discontinuity")
        while lo < hi:
            n = min(hi - lo, MAX_FRAME - len(buf))
            buf.extend(raw[lo - pos : lo - pos + n])
            lo += n
            if len(buf) == MAX_FRAME:
                flush()

    src_end = source.replay(collect)
    flush()
    require(src_end >= end and cursor == end, "catchup_wal_gap")


class ForwardReceiver:
    def __init__(self, legacy, parts, legacy_capacity, rollover_ready):
        require(
            legacy.identity == parts.identity
            and type(legacy_capacity) is int
            and legacy_capacity >= parts.window,
            "forward_wal_profile",
        )
        self.original = legacy
        self.parts = parts
        self.cap = legacy.identity.first_lsn + legacy_capacity
        self.rollover_ready = rollover_ready
        self.identity = legacy.identity

    def prefix(self, store, end):
        h = sha256()

        def observe(pos, raw):
            if pos < end:
                h.update(raw[: max(0, end - pos)])

        witnessed = store.replay(observe)
        require(witnessed >= end, "forward_wal_prefix_missing")
        return h.digest()

    def copy_tail(self, source, target, start, limit):
        copy_range(source, target, start, limit)
        require(target.verified_end() == limit, "forward_wal_catchup_failed")

    def synchronize(self):
        old = self.original.verified_end()
        new = self.parts.verified_end()
        require(self.identity.first_lsn <= old <= self.cap, "legacy_wal_capacity")
        shared = min(old, new)
        require(
            self.prefix(self.original, shared) == self.prefix(self.parts, shared),
            "divergent_independent_wal",
        )
        if new < old:
            self.copy_tail(self.original, self.parts, new, old)
            new = old
        elif old < min(new, self.cap):
            self.copy_tail(self.parts, self.original, old, min(new, self.cap))
        if new > self.cap:
            require(self.rollover_ready(), "forward_wal_qualification_pending")
        return new

    def accept(self, signer, pos, raw, challenge):
        require(
            type(challenge) is bytes and len(challenge) == 32, "forward_wal_challenge"
        )
        if raw:
            end = pos + len(raw)
            if end > self.cap:
                require(self.rollover_ready(), "forward_wal_qualification_pending")
            self.parts.append(pos, raw)
            if pos < self.cap:
                self.original.append(pos, raw[: min(len(raw), self.cap - pos)])
        else:
            # The enclosing session already independently authenticated the whole history
            # before opening replication. A reconnect performs the full check again.
            require(self.synchronize() == pos, "forward_wal_position")
        return signer.sign(proof(self.identity, pos, raw, challenge))
