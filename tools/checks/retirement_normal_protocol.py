"""Fixture-only public/control lines; production binary-header limits stay fixed."""

import hashlib

from ops.retirement.export_protocol import Channel


def bounded_line(channel, maximum):
    """Read one line without consuming any following private binary payload."""
    if maximum not in {16384, 1024 * 1024}:
        raise ValueError("normal_fixture_line_limit_invalid")
    while b"\n" not in channel.pending:
        if len(channel.pending) > maximum:
            raise RuntimeError("normal_fixture_public_line_capacity")
        raw = channel.receive()
        if not raw:
            raise RuntimeError("normal_fixture_public_line_missing")
        channel.pending.extend(raw)
    line, _, pending = channel.pending.partition(b"\n")
    if len(line) > maximum:
        raise RuntimeError("normal_fixture_public_line_capacity")
    channel.pending = pending
    return bytes(line)


class SeedChannel(Channel):
    """Original native setup-log semantics, capped at1MiB including private output.

    Setup diagnostics may precede exact control markers. Completion still needs
    the unchanged receipt frame, all actual seed assertions and a zero child exit.
    Only a constant-size diagnostic digest/count leaves RAM, never raw lines.
    """

    def __init__(self, process, deadline):
        super().__init__(process, deadline)
        self.received = 0
        self.diagnostic_count = 0
        self.diagnostic_digest = hashlib.sha256()
        self.last_category = None

    def receive(self):
        raw = super().receive()
        self.received += len(raw)
        if self.received > 1024 * 1024:
            raise RuntimeError("native_fixture_output_capacity")
        return raw

    def next_line(self):
        line = bounded_line(self, 1024 * 1024)
        if line.startswith((b"NATIVE_", b"NORMAL_", b"READY_")) and len(line) > 128:
            raise RuntimeError("retirement_export_header_capacity")
        return line

    def diagnostic(self, line):
        self.diagnostic_count += 1
        self.diagnostic_digest.update(len(line).to_bytes(4, "big"))
        self.diagnostic_digest.update(line)
        if line.startswith((b"NATIVE_", b"NORMAL_", b"READY_")):
            self.last_category = "unknown_control"
            raise RuntimeError("normal_fixture_unknown_seed_control")
        if line.startswith(b"Traceback "):
            self.last_category = "child_traceback"
            raise RuntimeError("normal_fixture_seed_child_traceback")
        if line.startswith(b"{"):
            self.last_category = "unexpected_public_result"
            raise RuntimeError("normal_fixture_seed_unexpected_public_result")
        self.last_category = (
            "pool_connection_diagnostic"
            if line.startswith(b"error connecting in ")
            else "setup_diagnostic"
        )

    def public_diagnostics(self):
        return {
            "diagnostic_lines": self.diagnostic_count,
            "diagnostic_sha256": self.diagnostic_digest.hexdigest(),
            "last_category": self.last_category,
        }
