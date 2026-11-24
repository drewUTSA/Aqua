"""Append-only station listener for an operator-provided private tunnel."""

import argparse
from ctypes import (
    POINTER,
    Structure,
    byref,
    c_ubyte,
    cast,
    create_string_buffer,
    memset,
    string_at,
)
from ctypes import wintypes
import hmac
import os
from pathlib import Path
import socket
import sys
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
if __package__:
    from .channel import FRAME_BYTES, respond
    from .journal import Witness
    from .receive import read_profile
else:
    from channel import FRAME_BYTES, respond
    from journal import Witness
    from receive import read_profile


def read_frame(connection):
    deadline = time.monotonic() + 2
    data = bytearray()
    while len(data) <= FRAME_BYTES:
        connection.settimeout(max(0, deadline - time.monotonic()))
        block = connection.recv(FRAME_BYTES + 1 - len(data))
        if not block:
            break
        data.extend(block)
    if len(data) != FRAME_BYTES:
        raise ValueError("checkpoint_witness_frame")
    return bytes(data)


def serve_connection(connection, journal, generation, service_public, station_key):
    frame = read_frame(connection)
    receipt = respond(journal, generation, service_public, station_key, frame)
    connection.settimeout(1)
    connection.sendall(receipt)


def load_station_key(identity, witness_public):
    """Open only this installation's CurrentUser DPAPI blob in the separate vault."""
    if sys.platform != "win32":
        raise ValueError("checkpoint_witness_requires_windows_custody")
    from ctypes import WinDLL
    from retirement.fingerprints import canonical_uuid

    canonical_uuid(identity.installation)
    path = (
        Path(os.environ["LOCALAPPDATA"])
        / "Aqua"
        / "RecoveryIdentities"
        / ("witness-" + identity.installation + ".dpapi")
    )
    if path.resolve(strict=True) != path or path.stat().st_nlink != 1:
        raise ValueError("checkpoint_witness_key_path")
    with path.open("rb") as file:
        wrapped = file.read(4097)
    if not 0 < len(wrapped) <= 4096:
        raise ValueError("checkpoint_witness_key_size")

    class Blob(Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", POINTER(c_ubyte))]

    kernel = WinDLL("Kernel32.dll", use_last_error=True)
    crypt = WinDLL("Crypt32.dll", use_last_error=True)
    unlock = crypt.CryptUnprotectData
    unlock.argtypes = [
        POINTER(Blob),
        POINTER(wintypes.LPWSTR),
        POINTER(Blob),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        POINTER(Blob),
    ]
    unlock.restype = wintypes.BOOL
    release = kernel.LocalFree
    release.argtypes = [wintypes.HLOCAL]
    release.restype = wintypes.HLOCAL
    buffer = create_string_buffer(wrapped)
    encrypted = Blob(len(wrapped), cast(buffer, POINTER(c_ubyte)))
    private = Blob()
    if not unlock(byref(encrypted), None, None, None, None, 1, byref(private)):
        raise ValueError("checkpoint_witness_key_unavailable")
    try:
        if private.size != 32:
            raise ValueError("checkpoint_witness_key_size")
        key = Ed25519PrivateKey.from_private_bytes(string_at(private.data, 32))
        if not hmac.compare_digest(key.public_key().public_bytes_raw(), witness_public):
            raise ValueError("checkpoint_witness_key_pin")
        return key
    finally:
        memset(private.data, 0, private.size)
        release(cast(private.data, wintypes.HLOCAL))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    parser.add_argument("--profile-sha256", required=True)
    parser.add_argument("--generation", required=True, type=int)
    parser.add_argument("--service-public-key", required=True)
    parser.add_argument("--witness-public-key", required=True)
    parser.add_argument("--loopback-port", required=True, type=int)
    args = parser.parse_args()
    identity = read_profile(args.profile, args.profile_sha256)
    service_public, witness_public = (
        bytes.fromhex(args.service_public_key),
        bytes.fromhex(args.witness_public_key),
    )
    if (
        not 0 < args.generation < 2**63 - 1
        or not 1024 <= args.loopback_port <= 65535
        or len(witness_public) != 32
        or len(service_public) != 32
        or len({identity.public_key, service_public, witness_public}) != 3
    ):
        parser.error("invalid station pins")
    journal = Witness(args.profile.with_name("checkpoint.sqlite3"), identity)
    key = load_station_key(identity, witness_public)
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", args.loopback_port))
        listener.listen(4)
        while True:
            conn, _ = listener.accept()
            with conn:
                try:
                    serve_connection(
                        conn, journal, args.generation, service_public, key
                    )
                except Exception:
                    # No response can signify a successful append; the publisher retries.
                    continue


if __name__ == "__main__":
    main()
