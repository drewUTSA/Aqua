"""Validate a bounded stored public JSON result without numerically rewriting it."""

from decimal import Decimal
import json

from privacy.policy import MAX_RESULT_FRAGMENT_BYTES

FIELDS = frozenset(
    {"status", "sql", "model", "message", "tables", "visualizations", "kpis", "error"}
)


def refuse_constant(_value):
    raise ValueError("export_result_invalid")


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("export_result_invalid")
        value[key] = item
    return value


def validated_bytes(source: object) -> bytes:
    """Input must already be grant-filtered, closed public-field SQL projection.

    Return original UTF-8 bytes, preserving exact number tokens and chart metadata.
    This validator does not authorize an owner, grant access or export arbitrary
    nested model/provider objects. The source query must be explicitly reviewed.
    """
    if type(source) is not str:
        raise ValueError("export_result_invalid")
    raw = source.encode("utf-8")
    if not 1 <= len(raw) <= MAX_RESULT_FRAGMENT_BYTES:
        raise ValueError("export_result_too_large")
    try:
        value = json.loads(
            source,
            parse_float=Decimal,
            parse_constant=refuse_constant,
            object_pairs_hook=unique_object,
        )
    except (ValueError, TypeError, RecursionError):
        raise ValueError("export_result_invalid") from None
    if (
        type(value) is not dict
        or set(value) != FIELDS
        or value["status"] not in {"success", "error"}
        or any(type(value[key]) is not str for key in ("sql", "model", "message"))
        or any(
            type(value[key]) is not list for key in ("tables", "visualizations", "kpis")
        )
        or value["error"] is not None
        and type(value["error"]) is not dict
    ):
        raise ValueError("export_result_invalid")
    return raw
