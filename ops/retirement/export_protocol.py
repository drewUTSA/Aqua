"""Finite private binary frames; archive/key plaintext never enters a log."""

import hashlib
import os
import select
import struct
import time

MAX_DUMP = 128 * 1024 * 1024
MAX_ARCHIVE = 193 * 1024 * 1024


class Channel:
    def __init__(self, process, deadline: float):
        self.process, self.deadline, self.pending = process, deadline, bytearray()
        os.set_blocking(process.stdout.fileno(), False)
        os.set_blocking(process.stdin.fileno(), False)

    def remaining(self) -> float:
        value = self.deadline - time.monotonic()
        if value <= 0:
            raise RuntimeError("retirement_export_protocol_deadline")
        return value

    def receive(self) -> bytes:
        while True:
            ready, _, _ = select.select(
                [self.process.stdout], [], [], min(0.2, self.remaining())
            )
            if ready:
                return os.read(self.process.stdout.fileno(), 65536)

    def line(self) -> bytes:
        while b"\n" not in self.pending:
            if len(self.pending) > 128:
                raise RuntimeError("retirement_export_header_capacity")
            raw = self.receive()
            if not raw:
                raise RuntimeError("retirement_export_header_missing")
            self.pending.extend(raw)
        line, _, self.pending = self.pending.partition(b"\n")
        if len(line) > 128:
            raise RuntimeError("retirement_export_header_capacity")
        return bytes(line)

    def write(self, raw: bytes) -> None:
        pending = memoryview(raw)
        while pending:
            _, ready, _ = select.select(
                [], [self.process.stdin], [], min(0.2, self.remaining())
            )
            if ready:
                count = os.write(self.process.stdin.fileno(), pending[:65536])
                pending = pending[count:]

    def exact(self, count: int, sink) -> str:
        digest = hashlib.sha256()
        while count:
            if not self.pending:
                raw = self.receive()
                if not raw:
                    raise RuntimeError("retirement_export_archive_truncated")
                self.pending.extend(raw)
            length = min(count, len(self.pending))
            chunk = bytes(self.pending[:length])
            del self.pending[:length]
            count -= length
            if sink.write(chunk) != len(chunk):
                raise RuntimeError("retirement_export_short_output_write")
            digest.update(chunk)
        return digest.hexdigest()


def archive(channel: Channel, dump, sink) -> dict:
    """Forward only the declared bounded tar, never internal control messages."""
    if channel.line() != b"AUTHORITY_DUMP":
        raise RuntimeError("retirement_export_dump_not_requested")
    raw = dump()
    if (
        type(raw) is not bytes
        or not 5 < len(raw) <= MAX_DUMP
        or not raw.startswith(b"PGDMP")
    ):
        raise RuntimeError("retirement_export_dump_invalid")
    channel.write(struct.pack("!Q", len(raw)))
    channel.write(raw)
    header = channel.line().split(b" ")
    if len(header) != 2 or header[0] != b"ARCHIVE" or not header[1].isdigit():
        raise RuntimeError("retirement_export_archive_header_invalid")
    size = int(header[1])
    if not 0 < size <= MAX_ARCHIVE:
        raise RuntimeError("retirement_export_archive_capacity")
    digest = channel.exact(size, sink)
    if channel.pending or channel.receive():
        raise RuntimeError("retirement_export_trailing_payload")
    if channel.process.wait(timeout=max(0.01, channel.remaining())) != 0:
        raise RuntimeError("retirement_export_peer_failed")
    return {"plaintext_bytes": size, "plaintext_sha256": digest}
