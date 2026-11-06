"""Closed original retirement-manifest bytes; no I/O or provider work.

The app stores these bounded bytes immutably before preparing the independent
header. Lost originals cannot be replaced by a smaller set after restore.
Only HMAC fingerprints and original server-selected metadata are encoded.
"""

from datetime import datetime, timezone
import struct
from uuid import UUID

from retirement.fingerprints import canonical_uuid
from retirement.intents import Intent
from retirement.pages import INITIAL, Manifest, decode, page_digest

MAGIC = b"AQUAMF1\x00"
HEADER_BYTES = 141
ENTRY_BYTES = 114
MAX_ORIGINAL_BYTES = 32 * 1024 * 1024
MAX_ENTRIES = 100000
EPOCH = datetime(2000, 1, 1, tzinfo=timezone.utc)


class ManifestUnavailable(RuntimeError):
    def __init__(self):
        super().__init__("retirement_original_manifest_unavailable")


def _header(record):
    if type(record) is not Intent:
        raise ManifestUnavailable()
    delta = record.created_at - EPOCH
    microseconds = (
        delta.days * 86400000000 + delta.seconds * 1000000 + delta.microseconds
    )
    return (
        MAGIC
        + b"".join(
            UUID(value).bytes
            for value in (record.installation, record.owner, record.intent, record.job)
        )
        + struct.pack(
            "!qBQQQI",
            microseconds,
            2 if record.scope == "account_v1" else 1,
            record.history_floor,
            record.privacy_floor,
            record.auth_floor,
            record.fingerprint_count,
        )
        + record.fingerprint_root
    )


def _validate(record, value, key_id):
    canonical_uuid(key_id)
    if (
        type(value) is not Manifest
        or type(value.count) is not int
        or not 0 <= value.count <= MAX_ENTRIES
        or value.count != record.fingerprint_count
        or value.root != record.fingerprint_root
        or type(value.root) is not bytes
        or len(value.root) != 32
        or type(value.pages) is not tuple
        or len(value.pages) != (value.count + 127) // 128
        or HEADER_BYTES + value.count * ENTRY_BYTES > MAX_ORIGINAL_BYTES
    ):
        raise ManifestUnavailable()
    previous, root, amount = None, INITIAL, 0
    for ordinal, page in enumerate(value.pages):
        if type(page) is not tuple or len(page) != min(128, value.count - amount):
            raise ManifestUnavailable()
        for entry in page:
            _, fingerprint = decode(entry)
            if (
                fingerprint.key_id != key_id
                or previous is not None
                and entry <= previous
            ):
                raise ManifestUnavailable()
            previous = entry
        root = page_digest(root, ordinal, page)
        amount += len(page)
    if amount != value.count or root != value.root:
        raise ManifestUnavailable()


def encode_original(record, value, *, key_id):
    """Max11,400,141 bytes under the separate32MiB storage column cap."""
    try:
        header = _header(record)
        _validate(record, value, key_id)
        result = header + b"".join(entry for page in value.pages for entry in page)
        if len(header) != HEADER_BYTES or len(result) > MAX_ORIGINAL_BYTES:
            raise ManifestUnavailable()
        return result
    except (TypeError, ValueError, OverflowError, AttributeError):
        raise ManifestUnavailable() from None


def decode_original(raw, record, *, key_id):
    """Check identity/count/length BEFORE allocating decoded pages; no sorting."""
    try:
        canonical_uuid(key_id)
        header = _header(record)
        if (
            type(raw) is not bytes
            or not HEADER_BYTES <= len(raw) <= MAX_ORIGINAL_BYTES
            or raw[:HEADER_BYTES] != header
            or len(raw) != HEADER_BYTES + record.fingerprint_count * ENTRY_BYTES
        ):
            raise ManifestUnavailable()
        pages, page = [], []
        root, previous = INITIAL, None
        for index in range(record.fingerprint_count):
            start = HEADER_BYTES + index * ENTRY_BYTES
            entry = raw[start : start + ENTRY_BYTES]
            _, fingerprint = decode(entry)
            if (
                fingerprint.key_id != key_id
                or previous is not None
                and entry <= previous
            ):
                raise ManifestUnavailable()
            previous = entry
            page.append(entry)
            if len(page) == 128 or index + 1 == record.fingerprint_count:
                items = tuple(page)
                root = page_digest(root, len(pages), items)
                pages.append(items)
                page = []
        result = Manifest(record.fingerprint_count, root, tuple(pages))
        _validate(record, result, key_id)
        return result
    except (TypeError, ValueError, OverflowError, AttributeError):
        raise ManifestUnavailable() from None
