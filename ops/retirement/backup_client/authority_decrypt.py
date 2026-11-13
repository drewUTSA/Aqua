"""Authenticated age output stays bounded in RAM; no plaintext file is opened."""

import os
import select
import subprocess
import time

from authority_bridge import archive, stream


def decrypt_ram(ciphertext, identity, *, seconds=120):
    stream.require(0 < seconds <= 120, "authority_decrypt_budget_invalid")
    stream.private_file(ciphertext, maximum=archive.MAX_ARCHIVE + 1024**2)
    stream.private_file(identity, maximum=65536)
    process = None
    output = bytearray()
    deadline = time.monotonic() + seconds
    try:
        process = subprocess.Popen(
            [
                stream.age_binary(),
                "-d",
                "-i",
                str(identity),
                "-o",
                "-",
                str(ciphertext),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        os.set_blocking(process.stdout.fileno(), False)
        while True:
            remaining = deadline - time.monotonic()
            stream.require(remaining > 0, "authority_decrypt_deadline")
            readable, _, _ = select.select(
                [process.stdout], [], [], min(0.2, remaining)
            )
            if not readable:
                continue
            chunk = os.read(
                process.stdout.fileno(),
                min(stream.CHUNK, archive.MAX_ARCHIVE + 1 - len(output)),
            )
            if not chunk:
                break
            output.extend(chunk)
            stream.require(
                len(output) <= archive.MAX_ARCHIVE, "authority_decrypt_capacity"
            )
        stream.require(
            process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
            "authority_authenticated_decryption_failed",
        )
        stream.require(bool(output), "authority_archive_empty")
        return bytes(output)
    finally:
        try:
            stream.stop_owned(process)
        finally:
            if process is not None and process.stdout is not None:
                process.stdout.close()
            output.clear()
