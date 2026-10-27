"""Build a small server-owned chart contract from an already authorized result.

Descriptors contain table references, never Plotly configuration or executable
content. A refusal preserves the complete table instead of silently reducing,
rounding, grouping or sampling financial values to make a chart fit.
"""

from collections.abc import Mapping, Sequence
from decimal import Decimal
import hashlib
import json
import math
import re
from typing import Any
from nl2sql.pipeline import Answer
from nl2sql.schema import Schema
from nl2sql.visual_axes import AxisError, RESERVED, axis_for
from nl2sql.visual_intent import intent_for
from nl2sql.visual_units import units_for

MAX_BAR_ROWS = 50
MAX_POINTS = 500
MAX_PRESENTATION_BYTES = 16000


def _number(value: Any) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        return False
    if isinstance(value, int):
        return abs(value) <= 2**53 - 1
    if not math.isfinite(value):
        return False
    return not (
        isinstance(value, float) and value.is_integer() and abs(value) > 2**53 - 1
    )


def presentation_for(
    answer: Answer,
    response: dict[str, Any],
    metadata: dict[str, Any],
    *,
    context: Sequence[Mapping[str, Any]] = (),
    schema: Schema | None = None,
) -> dict[str, Any]:
    """Offer one bounded chart or an explicit safe table/summary fallback.

    The P07 metadata vocabulary is deliberately unchanged for renderer rollback.
    Every new field is opt-in workspace presentation; legacy query JSON stays
    byte-shape compatible and old saved results keep their table alternative.
    """
    intent = intent_for(answer.question, context)
    base = {
        "version": 1,
        "intent": intent,
        "default_view": "table",
        "reason": "unsupported_shape",
        "charts": [],
    }

    def fallback(reason: str, view: str = "table") -> dict[str, Any]:
        return {**base, "reason": reason, "default_view": view}

    # Preserve the whole-result precision suppression in the P07 renderer.
    if metadata.get("exact_values") or any(
        isinstance(value, float) and value.is_integer() and abs(value) > 2**53 - 1
        for row in answer.rows
        for value in row
    ):
        return fallback("precision_limit")
    if intent == "text":
        return fallback("ordinary_text", "summary")
    if not answer.rows:
        return fallback("no_rows")
    if len(answer.rows) == 1:
        return fallback("scalar_result", "summary")
    if len(answer.rows) > 1000 or not 1 <= len(answer.columns) <= 64:
        return fallback("point_limit")
    tables = response.get("tables", [])
    if len(tables) != 1 or tables[0].get("id") != "result":
        return fallback("unsupported_shape")
    columns = tables[0].get("columns", [])
    keys = [column.get("key") for column in columns]
    if (
        len(keys) != len(answer.columns)
        or any(not isinstance(key, str) or not key or len(key) > 256 for key in keys)
        or len(set(keys)) != len(keys)
    ):
        return fallback("invalid_axis")
    if any(key in RESERVED for key in keys):
        return fallback("invalid_axis")
    if any(len(row) != len(keys) for row in answer.rows):
        return fallback("invalid_axis")
    try:
        axis = axis_for(answer, keys)
    except (AxisError, ValueError, OverflowError):
        return fallback("invalid_axis")
    if axis is None:
        return fallback("unsupported_shape")
    measures = []
    for index, name in enumerate(answer.columns):
        if (
            index in axis.indices
            or name.lower() == "id"
            or name.lower().endswith("_id")
        ):
            continue
        present = [row[index] for row in answer.rows if row[index] is not None]
        if present and all(_number(value) for value in present):
            measures.append(index)
    if not 1 <= len(measures) <= 2:
        return fallback("unsupported_shape")
    if any(keys[index] in RESERVED for index in (*axis.indices, *measures)):
        return fallback("invalid_axis")
    if len(answer.rows) * len(measures) > MAX_POINTS or (
        axis.chart_type == "bar" and len(answer.rows) > MAX_BAR_ROWS
    ):
        return fallback("point_limit")
    units = units_for(answer, schema)
    if len(measures) == 2 and (
        units[measures[0]] is None or units[measures[0]] != units[measures[1]]
    ):
        return fallback("ambiguous_units")
    # A supported shape cannot silently substitute for a specifically requested
    # incompatible chart family (pie/heatmap/etc. remain table-accessible).
    if re.search(
        r"\b(?:pie|scatter|histogram|heatmap|stacked)\b", answer.question, re.I
    ):
        return fallback("unsupported_shape")
    requested = re.search(
        r"\b(bar|line)\s+(?:chart|plot|graph)\b", answer.question, re.I
    )
    if requested and requested[1].lower() != axis.chart_type:
        return fallback("unsupported_shape")
    series = [
        {
            "key": keys[index],
            "label": str(columns[index].get("label", keys[index]))[:80],
            "unit": units[index],
        }
        for index in measures
    ]
    signature = {
        "source": metadata.get("source"),
        "type": axis.chart_type,
        "x": axis.descriptor,
        "series": series,
        "query": hashlib.sha256(answer.sql.encode()).hexdigest(),
        "schema": (
            hashlib.sha256(schema.to_prompt().encode()).hexdigest()
            if schema is not None
            else None
        ),
        "column_types": [
            columns[index].get("type") for index in (*axis.indices, *measures)
        ],
        "axis_values": [
            [tables[0]["rows"][row][keys[index]] for index in axis.indices]
            for row in axis.order
        ],
    }
    compatibility = hashlib.sha256(
        json.dumps(signature, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    chart = {
        "id": "result-chart",
        "type": axis.chart_type,
        "title": answer.question[:160],
        "tableId": "result",
        "x": axis.descriptor,
        "series": series,
        "row_indices": list(axis.order),
        "missing": "gap",
        "reduction": "none",
        "input_rows": len(answer.rows),
        "output_points": len(answer.rows) * len(series),
        "downsampled": False,
        "compatibility_key": compatibility,
        "approximate": False,
    }
    result = {
        **base,
        "default_view": "chart",
        "reason": "requested_visual" if intent == "explicit" else "visual_followup",
        "charts": [chart],
    }
    if (
        len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode())
        > MAX_PRESENTATION_BYTES
    ):
        return fallback("point_limit")
    return result
