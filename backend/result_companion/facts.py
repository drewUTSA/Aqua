"""Pure saved-field checks; source text is data, never authority or instructions."""

from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, InvalidOperation
import json
import math
import re

MAX_SAFE = 2**53 - 1
NUMERIC = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
CHECKS = {
    "returned_subset": "This result is truncated. These checks cover only the returned rows; ask for an aggregate/count or narrower scope before treating the list as complete.",
    "missing_values": "Some returned rows have no value in this field. Decide whether missing values should be excluded or shown separately before comparing.",
    "units_unknown": "The field unit is unspecified. Confirm its definition and unit before using it for a financial comparison.",
    "freshness_unknown": "Source freshness is unavailable. The saved generation time does not establish how current the source data is.",
    "scope_unknown": "Filters and aggregation are unspecified. Review the original question and SQL before assuming what one returned row represents.",
    "precision_unverified": "This older saved result has no verified precision descriptor. Numeric extrema are unavailable; use its existing table and verify important figures against the source.",
}


class ResultFactsError(ValueError):
    """Fixed failure only; no source fields or values in diagnostics."""


def require(value):
    if not value:
        raise ResultFactsError("saved_result_invalid")


def text(value, characters, maximum, *, multiline=False):
    require(type(value) is str and 0 < len(value) <= characters)
    require(len(value.encode("utf-8")) <= maximum)
    require(
        all(ord(c) >= 32 and ord(c) != 127 or multiline and c in "\n\t" for c in value)
    )
    return value


def encoded(value):
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def timestamp(value):
    require(type(value) is str and len(value) <= 40)
    try:
        parsed = datetime.fromisoformat(value)
        require(parsed.tzinfo is not None and parsed.utcoffset() is not None)
    except ValueError:
        raise ResultFactsError("saved_result_invalid") from None
    return value


def numeric(value, exact=None):
    require(type(value) in (int, float))
    require(type(value) is int or math.isfinite(value))
    source = str(value) if exact is None else exact
    if exact is not None:
        require(
            type(source) is str and len(source) <= 256 and NUMERIC.fullmatch(source)
        )
    try:
        number = Decimal(source)
    except (InvalidOperation, ValueError):
        raise ResultFactsError("saved_result_invalid") from None
    require(
        number.is_finite()
        and number.adjusted() <= 255
        and number.as_tuple().exponent >= -255
    )
    shown = source if exact is not None else format(number, "f")
    require(len(shown) <= 256 and NUMERIC.fullmatch(shown))
    return shown, number


def descriptor(response, columns, rows, check):
    """Validate original v1 precision pointers without trusting display heuristics."""
    if "result_metadata" not in response:
        return None, {}
    value = response["result_metadata"]
    require(
        type(value) is dict
        and set(value)
        == {
            "version",
            "source",
            "generated_at",
            "filters",
            "truncated",
            "max_rows",
            "aggregation",
            "column_units",
            "exact_values",
        }
    )
    require(type(value["version"]) is int and value["version"] == 1)
    source = value["source"]
    require(type(source) is dict and set(source) == {"id", "freshness_at"})
    require(
        type(source["id"]) is str
        and re.fullmatch(r"[a-f0-9]{64}", source["id"])
        and source["freshness_at"] is None
    )
    timestamp(value["generated_at"])
    require(value["filters"] is None and value["aggregation"] == "unknown")
    require(
        type(value["truncated"]) is bool
        and type(value["max_rows"]) is int
        and value["max_rows"] == 1000
    )
    units, exact = value["column_units"], value["exact_values"]
    require(
        type(units) is dict
        and set(units) == set(columns)
        and all(unit is None for unit in units.values())
    )
    require(
        type(exact) is list and len(exact) <= 1024 and len(encoded(value)) <= 160000
    )
    pointers = {}
    for entry in exact:
        check()
        require(
            type(entry) is dict and set(entry) == {"row", "column", "value", "kind"}
        )
        row, key, shown, kind = (
            entry[name] for name in ("row", "column", "value", "kind")
        )
        require(
            type(row) is int
            and 0 <= row < len(rows)
            and type(key) is str
            and key in columns
        )
        require(type(kind) is str and kind in {"integer", "decimal"})
        require((row, key) not in pointers)
        raw = rows[row][key]
        shown, number = numeric(raw, shown)
        if kind == "integer":
            require(re.fullmatch(r"-?(?:0|[1-9][0-9]*)", shown))
            require(int(shown) == raw if type(raw) is int else float(number) == raw)
        else:
            require(
                number == Decimal(raw) if type(raw) is int else float(number) == raw
            )
        pointers[row, key] = shown
    return value, pointers


def build(
    response: dict, question: str, column_index: int, check: Callable[[], None]
) -> dict:
    check()
    require(
        type(response) is dict
        and response.get("status") == "success"
        and len(encoded(response)) <= 240000
    )
    question = text(question, 2000, 8000, multiline=True)
    tables = response.get("tables")
    require(type(tables) is list and len(tables) == 1 and type(tables[0]) is dict)
    table = tables[0]
    require(table.get("id") == "result")
    columns, rows = table.get("columns"), table.get("rows")
    require(
        type(columns) is list
        and 1 <= len(columns) <= 64
        and type(rows) is list
        and len(rows) <= 1000
    )
    require(type(column_index) is int and 0 <= column_index < len(columns))
    require(all(type(column) is dict and "key" in column for column in columns))
    keys = [text(column["key"], 256, 1024) for column in columns]
    require(len(set(keys)) == len(keys))
    require(all(type(row) is dict and set(row) == set(keys) for row in rows))
    meta, pointers = descriptor(response, keys, rows, check)
    column, key = columns[column_index], keys[column_index]
    label = text(column.get("label", key), 256, 1024)
    selected, kinds, missing = [], set(), 0
    for index, row in enumerate(rows):
        check()
        value = row[key]
        if value is None:
            missing += 1
            continue
        kind = (
            "boolean"
            if type(value) is bool
            else (
                "numeric"
                if type(value) in (int, float)
                else "text" if type(value) is str else "mixed"
            )
        )
        kinds.add(kind)
        if kind == "numeric":
            selected.append((index, value))
    kind = "empty" if not kinds else next(iter(kinds)) if len(kinds) == 1 else "mixed"
    comparison = None
    if meta is not None and kind == "numeric":
        converted = []
        for row, value in selected:
            check()
            unsafe_integer = abs(value) > MAX_SAFE and (
                type(value) is int or value.is_integer()
            )
            require(not unsafe_integer or (row, key) in pointers)
            converted.append((row, *numeric(value, pointers.get((row, key)))))

        def extreme(number):
            matches = [
                (row, shown) for row, shown, observed in converted if observed == number
            ]
            return {
                "value": matches[0][1],
                "ties": len(matches),
                "witness_rows": [row for row, _ in matches[:3]],
            }

        comparison = {
            "minimum": extreme(min(v for _, _, v in converted)),
            "maximum": extreme(max(v for _, _, v in converted)),
        }
    checks = []
    if meta is not None and meta["truncated"]:
        checks.append("returned_subset")
    if missing:
        checks.append("missing_values")
    checks += ["units_unknown", "freshness_unknown", "scope_unknown"]
    if meta is None:
        checks.append("precision_unverified")
    intents = (
        ["verify_scope"]
        + (["missing_values"] if missing else [])
        + (["compare_field"] if comparison else [])
    )
    result = {
        "method": "saved_result_rules",
        "status": "ready" if meta is not None else "limited",
        "question": question,
        "source": {
            "id": meta["source"]["id"] if meta else None,
            "generated_at": meta["generated_at"] if meta else None,
            "freshness_at": None,
        },
        "scope": {
            "basis": "returned_rows_only",
            "truncated": meta["truncated"] if meta else None,
            "max_rows": 1000 if meta else None,
            "filters": "unknown",
            "aggregation": "unknown",
            "precision": "sidecar_preferred" if meta else "legacy_unverified",
        },
        "field": {
            "index": column_index,
            "key": key,
            "label": label,
            "kind": kind,
            "unit": None,
        },
        "counts": {
            "returned_rows": len(rows),
            "missing_values": missing,
            "non_missing_values": len(rows) - missing,
        },
        "numeric": comparison,
        "checks": [{"id": key, "text": CHECKS[key]} for key in checks],
        "followup_intents": intents,
        "execution_enabled": False,
    }
    check()
    require(len(encoded(result)) <= 32000)
    return result
