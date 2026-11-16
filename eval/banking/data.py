"""Small strict data boundary for the separate offline banking domain."""

import hashlib
import json
import re
import unicodedata
from uuid import UUID

MAX_BYTES = 32768
MAX_CLOCK = 9007199254740991


class BankingDenied(ValueError):
    """Fixed categories contain no prompt, policy, customer or bank data."""


def require(condition, code):
    if not condition:
        raise BankingDenied(code)


def unique(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate_field")
        result[key] = value
    return result


def constant(_):
    raise BankingDenied("nonfinite_number")


def floating(_):
    raise BankingDenied("unsupported_number")


def load(raw):
    require(type(raw) is bytes and 0 < len(raw) <= MAX_BYTES, "input_budget")
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=constant,
            parse_float=floating,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise BankingDenied("invalid_json") from None


def encode(value):
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise BankingDenied("invalid_data") from None
    require(len(raw) <= MAX_BYTES, "output_budget")
    return raw


def fields(value, names, code="unknown_fields"):
    require(type(value) is dict and set(value) == set(names), code)


def identifier(value):
    return (
        type(value) is str and re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", value) is not None
    )


def revision(value):
    return type(value) is str and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def version(value):
    return (
        type(value) is str
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", value) is not None
    )


def uuid(value):
    try:
        return type(value) is str and str(UUID(value)) == value
    except ValueError:
        return False


def clock(value):
    return type(value) is int and 0 <= value <= MAX_CLOCK


def text(value, maximum, *, multiline=False):
    try:
        return (
            type(value) is str
            and bool(value.strip())
            and len(value.encode()) <= maximum
            and all(
                unicodedata.category(character) not in {"Cc", "Cf", "Cs"}
                or multiline
                and character in "\n\t"
                for character in value
            )
        )
    except UnicodeError:
        return False


def digest(raw):
    return hashlib.sha256(raw).hexdigest()
