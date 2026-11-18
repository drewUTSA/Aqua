"""Pure note validation/projection; user text is never an authority or formula."""

from datetime import datetime
import hashlib
import json
import unicodedata
from uuid import UUID

from context_notes.policy import (
    KINDS,
    MAX_BODY_BYTES,
    MAX_BODY_UNITS,
    MAX_LABEL_BYTES,
    MAX_LABEL_CHARACTERS,
    MAX_REVISION,
)


def encode(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
    ).encode("utf-8")


def identifier(value: object) -> str:
    if type(value) is not str:
        raise ValueError("note_identifier_invalid")
    try:
        parsed = UUID(value)
    except ValueError:
        raise ValueError("note_identifier_invalid") from None
    if str(parsed) != value:
        raise ValueError("note_identifier_invalid")
    return value


def revision(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_REVISION:
        raise ValueError("note_revision_invalid")
    return value


def text(value: object, *, label: bool = False) -> str:
    """Preserve bytes while enforcing the existing composer's UTF16 contract."""
    if type(value) is not str or not value.strip():
        raise ValueError("note_text_invalid")
    try:
        size = len(value.encode("utf-8"))
        units = len(value.encode("utf-16-le")) // 2
    except UnicodeError:
        raise ValueError("note_text_invalid") from None
    for char in value:
        category = unicodedata.category(char)
        if label and category in {"Zl", "Zp"}:
            raise ValueError("note_text_invalid")
        if category in {"Cc", "Cf", "Cs"} and not (not label and char in "\t\n"):
            raise ValueError("note_text_invalid")
    if label:
        if (
            len(value) > MAX_LABEL_CHARACTERS
            or size > MAX_LABEL_BYTES
            or value != value.strip()
        ):
            raise ValueError("note_text_invalid")
    elif units > MAX_BODY_UNITS or size > MAX_BODY_BYTES:
        raise ValueError("note_text_invalid")
    return value


def content(kind: object, label: object, body: object) -> dict:
    if type(kind) is not str or kind not in KINDS:
        raise ValueError("note_kind_invalid")
    return {"kind": kind, "label": text(label, label=True), "body": text(body)}


def scope_id(
    owner: str, dataset: str, grant_version: int, auth_epoch: int, history: int
) -> str:
    """A checksum binds delivery, never supplies permission to a later call."""
    return hashlib.sha256(
        encode([owner, dataset, grant_version, auth_epoch, history])
    ).hexdigest()


def available(item: dict, *, allowed: bool, dataset: str, version: int) -> bool:
    return bool(
        allowed and item["dataset_key"] == dataset and item["grant_version"] == version
    )


def timestamp(value: object) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("note_timestamp_invalid")
    return value.isoformat()


def metadata(item: dict, *, allowed: bool) -> dict:
    """An unavailable scope reveals only the owned ID/revision and fixed copy."""
    if allowed and item["kind"] not in KINDS:
        raise ValueError("note_kind_invalid")
    return {
        "id": identifier(str(item["id"])),
        "revision": revision(item["revision"]),
        "availability": "available" if allowed else "unavailable",
        "label": (
            text(item["label"], label=True) if allowed else "Unavailable saved context"
        ),
        "kind": item["kind"] if allowed else None,
        "created_at": timestamp(item["created_at"]) if allowed else None,
        "updated_at": timestamp(item["updated_at"]) if allowed else None,
    }


def note(item: dict) -> dict:
    return {
        "id": identifier(str(item["id"])),
        "revision": revision(item["revision"]),
        **content(item["kind"], item["label"], item["body"]),
        "created_at": timestamp(item["created_at"]),
        "updated_at": timestamp(item["updated_at"]),
    }
