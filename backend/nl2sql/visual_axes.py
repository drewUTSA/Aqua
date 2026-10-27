"""Bounded axes preserve compound identity and reject ambiguous time semantics."""

from dataclasses import dataclass
import datetime as dt
from decimal import Decimal
import json
import math
import re
from typing import Any
from nl2sql.pipeline import Answer

RESERVED = frozenset({"__proto__", "constructor", "prototype"})
_PARTS = frozenset({"year", "quarter", "month", "day", "week", "hour"})
_COMBINATIONS = (
    ("year",),
    ("year", "quarter"),
    ("year", "month"),
    ("year", "month", "day"),
)


@dataclass(frozen=True)
class Axis:
    descriptor: dict[str, Any]
    indices: tuple[int, ...]
    order: tuple[int, ...]
    chart_type: str


class AxisError(ValueError):
    """Only a fixed fallback category crosses the presentation boundary."""


def _ordered(keys: list[Any]) -> tuple[int, ...]:
    if len(set(keys)) != len(keys):
        raise AxisError("invalid_axis")
    return tuple(sorted(range(len(keys)), key=keys.__getitem__))


def axis_for(answer: Answer, keys: list[str]) -> Axis | None:
    """Find one unambiguous temporal or compound categorical axis.

    No chart grouping, bucketing or averaging occurs here. Duplicate x groups
    would otherwise make a renderer overlay rows and silently change meaning.
    """
    columns = list(zip(*answer.rows))
    present = [[value for value in column if value is not None] for column in columns]
    time = [
        i
        for i, values in enumerate(present)
        if values and all(isinstance(value, (dt.date, dt.datetime)) for value in values)
    ]
    parts = {
        name.lower(): i
        for i, name in enumerate(answer.columns)
        if name.lower() in _PARTS
    }
    if time:
        if len(time) != 1:
            raise AxisError("invalid_axis")
        index = time[0]
        values = list(columns[index])
        if any(value is None for value in values):
            raise AxisError("invalid_axis")
        if all(type(value) is dt.date for value in values):
            kind, zone, identities = (
                "date",
                None,
                [value.toordinal() for value in values],
            )
        elif all(
            isinstance(value, dt.datetime)
            and value.utcoffset() is not None
            and value.utcoffset().total_seconds() % 60 == 0
            and value.microsecond % 1000 == 0
            for value in values
        ):
            kind, zone = "datetime", "UTC"
            identities = [value.astimezone(dt.timezone.utc) for value in values]
        else:
            raise AxisError("invalid_axis")
        return Axis(
            {
                "keys": [keys[index]],
                "kind": kind,
                "timezone": zone,
                "calendar_parts": [],
            },
            (index,),
            _ordered(identities),
            "line",
        )
    if parts:
        combination = tuple(
            part for part in ("year", "quarter", "month", "day") if part in parts
        )
        if combination not in _COMBINATIONS or set(combination) != set(parts):
            raise AxisError("invalid_axis")
        indices = tuple(parts[part] for part in combination)
        identities = []
        for row in answer.rows:
            selected = [row[index] for index in indices]
            if any(
                isinstance(value, bool)
                or not isinstance(value, (int, float, Decimal))
                or not math.isfinite(value)
                or value != int(value)
                for value in selected
            ):
                raise AxisError("invalid_axis")
            values = dict(zip(combination, map(int, selected)))
            try:
                dt.date(values["year"], values.get("month", 1), values.get("day", 1))
            except ValueError:
                raise AxisError("invalid_axis") from None
            if "quarter" in values and not 1 <= values["quarter"] <= 4:
                raise AxisError("invalid_axis")
            identities.append(tuple(values[part] for part in combination))
        return Axis(
            {
                "keys": [keys[index] for index in indices],
                "kind": "calendar",
                "timezone": None,
                "calendar_parts": list(combination),
            },
            indices,
            _ordered(identities),
            "line",
        )
    texts = [
        i
        for i, values in enumerate(present)
        if values and all(isinstance(value, str) for value in values)
    ]
    if not texts or len(texts) > 3:
        return None
    # Preserve source order. Type/position-bound tuples avoid joining labels
    # into an accidental group key (first/last name is a common example).
    identities = [
        json.dumps([row[i] for i in texts], ensure_ascii=False, separators=(",", ":"))
        for row in answer.rows
    ]
    if len(set(identities)) != len(identities):
        raise AxisError("invalid_axis")
    if any(
        row[i] is None or len(str(row[i])) > 256 for row in answer.rows for i in texts
    ):
        raise AxisError("invalid_axis")
    if len(texts) == 1 and all(
        re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) for value in columns[texts[0]]
    ):
        try:
            dates = [dt.date.fromisoformat(value) for value in columns[texts[0]]]
        except ValueError:
            raise AxisError("invalid_axis") from None
        return Axis(
            {
                "keys": [keys[texts[0]]],
                "kind": "date",
                "timezone": None,
                "calendar_parts": [],
            },
            tuple(texts),
            _ordered(dates),
            "line",
        )
    return Axis(
        {
            "keys": [keys[i] for i in texts],
            "kind": "category",
            "timezone": None,
            "calendar_parts": [],
        },
        tuple(texts),
        tuple(range(len(answer.rows))),
        "bar",
    )
