"""Fixed-width metadata-only fingerprint pages for the private SQL contract."""

from dataclasses import dataclass
import hashlib
import re
import struct
from uuid import UUID

from retirement.fingerprints import Fingerprint

VERSION = 1
PAYLOAD_BYTES = 114
PAGE_ITEMS = 128
MAX_FINGERPRINTS = 100000
INITIAL = hashlib.sha256(b"AQUA:retirement-pages:v1\x00").digest()
KINDS = {"google_subject": 1, "mailbox": 2}


def encode(dataset_key, fingerprint):
    if (
        type(dataset_key) is not str
        or not re.fullmatch(r"[a-f0-9]{64}", dataset_key)
        or type(fingerprint) is not Fingerprint
    ):
        raise ValueError("retirement_page_input_invalid")
    return (
        bytes([VERSION])
        + dataset_key.encode("ascii")
        + UUID(fingerprint.key_id).bytes
        + bytes([KINDS[fingerprint.kind]])
        + fingerprint.digest
    )


def decode(payload):
    if (
        type(payload) is not bytes
        or len(payload) != PAYLOAD_BYTES
        or payload[0] != VERSION
        or payload[81] not in KINDS.values()
    ):
        raise ValueError("retirement_page_payload_invalid")
    try:
        dataset = payload[1:65].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("retirement_page_payload_invalid") from None
    if not re.fullmatch(r"[a-f0-9]{64}", dataset):
        raise ValueError("retirement_page_payload_invalid")
    kind = next(name for name, value in KINDS.items() if value == payload[81])
    return dataset, Fingerprint(str(UUID(bytes=payload[65:81])), kind, payload[82:])


def page_digest(previous, ordinal, items):
    if (
        type(previous) is not bytes
        or len(previous) != 32
        or type(ordinal) is not int
        or not 0 <= ordinal < 782
        or type(items) is not tuple
        or not 1 <= len(items) <= PAGE_ITEMS
    ):
        raise ValueError("retirement_page_invalid")
    last = None
    for item in items:
        decode(item)
        if last is not None and item <= last:
            raise ValueError("retirement_page_order_invalid")
        last = item
    return hashlib.sha256(
        previous + struct.pack("!I", ordinal) + b"".join(items)
    ).digest()


@dataclass(frozen=True)
class Manifest:
    count: int
    root: bytes
    pages: tuple


def manifest(items):
    unique = set()
    for count, item in enumerate(items, 1):
        if count > MAX_FINGERPRINTS:
            raise ValueError("retirement_fingerprint_capacity")
        decode(item)
        unique.add(item)
    ordered = tuple(sorted(unique))
    pages, root = [], INITIAL
    for offset in range(0, len(ordered), PAGE_ITEMS):
        page = ordered[offset : offset + PAGE_ITEMS]
        root = page_digest(root, len(pages), page)
        pages.append(page)
    return Manifest(len(ordered), root, tuple(pages))
