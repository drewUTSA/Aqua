"""Offline companion data/choice qualification; caller claims are not authority."""

from dataclasses import dataclass
import json
import re
from uuid import UUID

from preferences.schema import OPTIONS

MAX_INPUT_BYTES = 32768
MAX_CONTEXT_BYTES = 16384
MAX_BLOCKS = 16
MAX_AGE_SECONDS = 3600
PREFERENCES = frozenset(
    {
        "locale",
        "timezone",
        "precision",
        "date_style",
        "time_format",
        "expanded_summaries",
    }
)
TOOLS = {
    "app_help": "aqua_help",
    "authorized_question": "owned_question",
    "monthly_trend": "dataset_metadata",
}
BINDING = {"actor_id", "scope_id", "dataset", "schema_revision"}


class CompanionDenied(ValueError):
    """Fixed error categories never echo private source content."""


@dataclass(frozen=True)
class Context:
    data: bytes
    binding: tuple[str, str, str, str]
    artifacts: tuple[tuple[str, str], ...]
    created_at: int
    expires_at: int


def _unique(items):
    result = {}
    for key, value in items:
        if key in result:
            raise CompanionDenied("duplicate_field")
        result[key] = value
    return result


def _load(raw):
    if type(raw) is not bytes or len(raw) > MAX_INPUT_BYTES:
        raise CompanionDenied("input_budget_invalid")
    try:
        return json.loads(raw, object_pairs_hook=_unique)
    except (ValueError, UnicodeError, RecursionError):
        raise CompanionDenied("input_invalid") from None


def _encode(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _text(value, limit):
    try:
        return (
            type(value) is str
            and bool(value.strip())
            and len(value.encode()) <= limit
            and all(ord(c) >= 32 or c in "\n\t" for c in value)
        )
    except UnicodeError:
        return False


def _identifier(value):
    return type(value) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value)


def _binding(actor_id, scope_id, dataset, schema_revision, now):
    try:
        canonical = all(
            type(v) is str and str(UUID(v)) == v for v in (actor_id, scope_id)
        )
    except ValueError:
        canonical = False
    if (
        not canonical
        or type(dataset) is not str
        or dataset not in {"bank", "pagila"}
        or type(schema_revision) is not str
        or not re.fullmatch(r"[a-f0-9]{64}", schema_revision)
        or type(now) is not int
        or not 0 <= now <= 9007199254740991
    ):
        raise CompanionDenied("caller_binding_invalid")
    return actor_id, scope_id, dataset, schema_revision


def _payload(kind, data):
    if type(data) is not dict:
        raise CompanionDenied("payload_invalid")
    valid = False
    if kind == "aqua_help" and set(data) == {"topic", "text"}:
        valid = data["topic"] in (
            "overview",
            "questions",
            "results",
            "privacy",
        ) and _text(data["text"], 2048)
    elif kind == "dataset_metadata" and set(data) == {"description", "tables"}:
        tables = data["tables"]
        valid = (
            _text(data["description"], 2048)
            and type(tables) is list
            and 1 <= len(tables) <= 16
            and all(_identifier(v) for v in tables)
            and len(set(tables)) == len(tables)
        )
    elif kind == "owned_question" and set(data) == {"question"}:
        valid = _text(data["question"], 8000) and len(data["question"]) <= 2000
    elif kind == "preference" and data and set(data) <= PREFERENCES:
        valid = all(
            type(v) is type(OPTIONS[k][0]) and v in OPTIONS[k] for k, v in data.items()
        )
    if not valid:
        raise CompanionDenied("payload_invalid")
