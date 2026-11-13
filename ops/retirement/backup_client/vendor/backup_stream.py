"""Bounded age pipelines; private dump plaintext remains in pipes and RAM."""

import hashlib
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import time

AGE = Path.home() / ".local/share/aqua-toolchain/age/1.3.2/bin/age"
AGE_SHA256 = "4012dfc2725883beafb710894af4f599b7a94f8c8e0f51f02cc96ab8df33915e"
MAX_PLAIN_BYTES = 512 * 1024**2
MAX_CIPHER_BYTES = MAX_PLAIN_BYTES + 1024**2
CHUNK = 65536


class BackupError(RuntimeError):
    """Only fixed operation categories may leave this controller."""


def require(condition: bool, code: str) -> None:
    if not condition:
        raise BackupError(code)


def private_file(
    path: Path | str, *, maximum: int = MAX_CIPHER_BYTES
) -> os.stat_result:
    info = Path(path).lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and info.st_nlink == 1
        and 0 < info.st_size <= maximum,
        "private_file_invalid",
    )
    return info


def age_binary() -> str:
    info = AGE.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_uid == os.getuid()
        and not info.st_mode & 0o022
        and hashlib.sha256(AGE.read_bytes()).hexdigest() == AGE_SHA256,
        "age_binary_integrity_failed",
    )
    return str(AGE)


def stop_owned(process: subprocess.Popen[bytes] | None) -> None:
    """Kill only the exact subprocess group created for this operation."""
    if process is None:
        return
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if process.poll() is not None:
            break
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            break
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            continue
    require(process.poll() is not None, "subprocess_cleanup_unconfirmed")


def bounded_metadata(
    command: list[str],
    data: bytes | None = None,
    *,
    seconds: float = 20,
    maximum: int = 16384,
) -> bytes:
    """Bound metadata while reading, including a noisy or stalled SSH helper."""
    require(0 < seconds <= 20 and 0 < maximum <= 16384, "metadata_budget_invalid")
    require(data is None or len(data) <= maximum, "metadata_input_limit")
    process = None
    pending = memoryview(data or b"")
    received = bytearray()
    deadline = time.monotonic() + seconds
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        os.set_blocking(process.stdin.fileno(), False)
        os.set_blocking(process.stdout.fileno(), False)
        if not pending:
            process.stdin.close()
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "metadata_deadline_exceeded")
            read, write, _ = select.select(
                [process.stdout],
                [process.stdin] if pending else [],
                [],
                min(0.2, remaining),
            )
            if write:
                pending = pending[os.write(process.stdin.fileno(), pending) :]
                if not pending:
                    process.stdin.close()
            if read:
                part = os.read(
                    process.stdout.fileno(), min(CHUNK, maximum + 1 - len(received))
                )
                if not part:
                    break
                received.extend(part)
                require(len(received) <= maximum, "metadata_output_limit")
        process.stdout.close()
        require(not pending, "metadata_input_incomplete")
        require(
            process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
            "metadata_process_failed",
        )
        return bytes(received)
    finally:
        stop_owned(process)


def encrypt_export(
    command: list[str],
    recipients: list[str],
    destination: Path | str,
    *,
    seconds: float = 120,
    maximum: int = MAX_PLAIN_BYTES,
) -> dict[str, int | str]:
    """Hash/export through a one-chunk buffer and encrypt to an exclusive file."""
    require(
        0 < seconds <= 120 and 0 < maximum <= MAX_PLAIN_BYTES, "stream_budget_invalid"
    )
    require(1 <= len(recipients) <= 4, "recipient_count_invalid")
    age = age_binary()
    destination = Path(destination)
    descriptor = os.open(
        destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    export = encrypt = None
    deadline = time.monotonic() + seconds
    size = 0
    digest = hashlib.sha256()
    success = False
    try:
        encrypt = subprocess.Popen(
            [age, *[value for item in recipients for value in ("-r", item)], "-o", "-"],
            stdin=subprocess.PIPE,
            stdout=descriptor,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        export = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        os.set_blocking(export.stdout.fileno(), False)
        os.set_blocking(encrypt.stdin.fileno(), False)
        pending = bytearray()
        ended = False
        while not ended or pending:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "export_deadline_exceeded")
            require(encrypt.poll() is None, "encryption_ended_early")
            read = [export.stdout] if not ended and len(pending) < CHUNK else []
            write = [encrypt.stdin] if pending else []
            readable, writable, _ = select.select(read, write, [], min(0.2, remaining))
            if readable:
                data = os.read(export.stdout.fileno(), CHUNK - len(pending))
                if not data:
                    ended = True
                else:
                    size += len(data)
                    require(size <= maximum, "export_byte_limit_exceeded")
                    digest.update(data)
                    pending.extend(data)
            if writable:
                sent = os.write(encrypt.stdin.fileno(), pending)
                del pending[:sent]
            require(
                os.fstat(descriptor).st_size <= MAX_CIPHER_BYTES,
                "cipher_byte_limit_exceeded",
            )
        export.stdout.close()
        require(
            export.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
            "export_process_failed",
        )
        require(size > 0, "export_empty")
        encrypt.stdin.close()
        require(
            encrypt.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
            "encryption_failed",
        )
        os.fsync(descriptor)
        success = True
    finally:
        try:
            try:
                stop_owned(export)
            finally:
                stop_owned(encrypt)
        finally:
            created = os.fstat(descriptor)
            os.close(descriptor)
            if not success:
                current = destination.lstat() if destination.exists() else None
                require(
                    current is None
                    or (current.st_dev, current.st_ino)
                    == (created.st_dev, created.st_ino),
                    "cipher_cleanup_ownership_changed",
                )
                if current is not None:
                    destination.unlink()
    return {"plaintext_bytes": size, "plaintext_sha256": digest.hexdigest()}


def decrypt_fingerprint(
    ciphertext: Path | str,
    identity: Path | str,
    *,
    seconds: float = 120,
    maximum: int = MAX_PLAIN_BYTES,
) -> dict[str, int | str]:
    """Authenticate every decrypted byte before returning a digest-only proof."""
    require(
        0 < seconds <= 120 and 0 < maximum <= MAX_PLAIN_BYTES, "stream_budget_invalid"
    )
    private_file(ciphertext)
    private_file(identity, maximum=65536)
    process = None
    size = 0
    digest = hashlib.sha256()
    deadline = time.monotonic() + seconds
    try:
        process = subprocess.Popen(
            [age_binary(), "-d", "-i", str(identity), "-o", "-", str(ciphertext)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            bufsize=0,
            start_new_session=True,
        )
        os.set_blocking(process.stdout.fileno(), False)
        while True:
            remaining = deadline - time.monotonic()
            require(remaining > 0, "decryption_deadline_exceeded")
            readable, _, _ = select.select(
                [process.stdout], [], [], min(0.2, remaining)
            )
            if not readable:
                continue
            data = os.read(process.stdout.fileno(), CHUNK)
            if not data:
                break
            size += len(data)
            require(size <= maximum, "decryption_byte_limit_exceeded")
            digest.update(data)
        process.stdout.close()
        require(
            process.wait(timeout=max(0.01, deadline - time.monotonic())) == 0,
            "authenticated_decryption_failed",
        )
    finally:
        stop_owned(process)
    return {"plaintext_bytes": size, "plaintext_sha256": digest.hexdigest()}
