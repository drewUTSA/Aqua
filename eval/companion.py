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


def assemble_context(raw, *, actor_id, scope_id, dataset, schema_revision, now):
    """Project explicitly reviewed data, never system instructions or auth proof."""
    binding = _binding(actor_id, scope_id, dataset, schema_revision, now)
    pack = _load(raw)
    if (
        type(pack) is not dict
        or set(pack) != BINDING | {"schemaVersion", "blocks"}
        or type(pack["schemaVersion"]) is not int
        or pack["schemaVersion"] != 1
    ):
        raise CompanionDenied("context_schema_invalid")
    expected = dict(
        zip(("actor_id", "scope_id", "dataset", "schema_revision"), binding)
    )
    if any(pack[k] != v for k, v in expected.items()):
        raise CompanionDenied("context_binding_invalid")
    blocks = pack["blocks"]
    if type(blocks) is not list or not 1 <= len(blocks) <= MAX_BLOCKS:
        raise CompanionDenied("block_budget_invalid")
    projected, artifacts, expiry = [], {}, now + MAX_AGE_SECONDS
    for block in blocks:
        if type(block) is not dict or set(block) != BINDING | {
            "id",
            "kind",
            "approved",
            "observed_at",
            "expires_at",
            "data",
        }:
            raise CompanionDenied("block_schema_invalid")
        if block["approved"] is not True or any(
            block[k] != v for k, v in expected.items()
        ):
            raise CompanionDenied("block_binding_invalid")
        key, kind = block["id"], block["kind"]
        if not _identifier(key) or key in artifacts or type(kind) is not str:
            raise CompanionDenied("artifact_invalid")
        observed, expires = block["observed_at"], block["expires_at"]
        if (
            type(observed) is not int
            or type(expires) is not int
            or not 0 <= observed <= now < expires <= observed + MAX_AGE_SECONDS
        ):
            raise CompanionDenied("context_stale")
        _payload(kind, block["data"])
        projected.append({"id": key, "kind": kind, "data": block["data"]})
        artifacts[key], expiry = kind, min(expiry, expires)
    data = _encode(
        {
            "schemaVersion": 1,
            "content_role": "untrusted_data",
            "dataset": dataset,
            "schema_revision": schema_revision,
            "blocks": projected,
        }
    )
    if len(data) > MAX_CONTEXT_BYTES:
        raise CompanionDenied("context_budget_invalid")
    return Context(data, binding, tuple(artifacts.items()), now, expiry)


def validate_choices(
    raw,
    *,
    context,
    actor_id,
    scope_id,
    dataset,
    schema_revision,
    now,
    available_capabilities=frozenset(),
    authorized_artifact_ids=frozenset(),
):
    """Validate closed offline choices only. No executor or live availability claim."""
    binding = _binding(actor_id, scope_id, dataset, schema_revision, now)
    if (
        type(context) is not Context
        or context.binding != binding
        or not context.created_at <= now < context.expires_at
    ):
        raise CompanionDenied("context_binding_invalid")
    artifacts = dict(context.artifacts)
    if (
        type(available_capabilities) is not frozenset
        or not available_capabilities <= TOOLS.keys()
        or type(authorized_artifact_ids) is not frozenset
        or not authorized_artifact_ids <= artifacts.keys()
    ):
        raise CompanionDenied("availability_invalid")
    request = _load(raw)
    if (
        type(request) is not dict
        or set(request) != {"schemaVersion", "choices"}
        or type(request["schemaVersion"]) is not int
        or request["schemaVersion"] != 1
    ):
        raise CompanionDenied("choice_schema_invalid")
    choices = request["choices"]
    if type(choices) is not list or len(choices) > 3:
        raise CompanionDenied("choice_budget_invalid")
    seen = set()
    for choice in choices:
        if type(choice) is not dict or set(choice) != {"capability_id", "artifact_id"}:
            raise CompanionDenied("choice_schema_invalid")
        capability, artifact = choice["capability_id"], choice["artifact_id"]
        if (
            type(capability) is not str
            or type(artifact) is not str
            or capability not in available_capabilities
            or artifact not in authorized_artifact_ids
            or artifacts[artifact] != TOOLS[capability]
            or capability in seen
        ):
            raise CompanionDenied("choice_denied")
        seen.add(capability)
    return _encode({"schemaVersion": 1, "choices": choices, "execution_enabled": False})
