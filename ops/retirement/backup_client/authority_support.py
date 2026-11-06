"""Frozen reviewed primitives and bounded operator cancellation."""

import hashlib
from pathlib import Path
import re
import signal
import sys

HERE = Path(__file__).resolve().parent


def reviewed_libraries():
    sys.path.insert(0, str(HERE / "vendor"))
    import authority_archive
    import backup_host
    import backup_stream
    from retirement.checkpoint import decode

    return authority_archive, backup_host, backup_stream, decode


archive, host, stream, decode = reviewed_libraries()

MAX_ARCHIVE = archive.MAX_ARCHIVE
HOLDERS = {"web", "analysis", "export", "download", "deletion", "mail", "publisher"}
TABLES = {"control", "owners", "intents", "pages", "fingerprints", "journal"}
HEX = re.compile(r"[a-f0-9]{64}\Z")


def require(value, code):
    if not value:
        raise stream.BackupError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Operation:
    """Cancellation raises once; owned pipeline finally blocks cannot be interrupted."""

    def __enter__(self):
        self.cancelled = False
        self.previous = {}
        for number in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            self.previous[number] = signal.getsignal(number)
            signal.signal(number, self.receive)
        return self

    def receive(self, number, frame):
        if not self.cancelled:
            self.cancelled = True
            raise stream.BackupError("authority_operation_cancelled")

    def __exit__(self, kind, value, traceback):
        for number, handler in self.previous.items():
            signal.signal(number, handler)
