"""Versioned workspace provenance retains values a JavaScript number would lose.

The legacy response stays compatible. Only the workspace adapter opts into this
metadata before response conversion; consumers must prefer these exact cells.
Unknown freshness, filters, aggregation and units remain explicitly unknown.
"""

from datetime import datetime, timezone
from decimal import Decimal
import json
import math
import re
from typing import Any

from nl2sql.execute import DEFAULT_MAX_ROWS
from nl2sql.pipeline import Answer
from nl2sql.response import _unique_keys

MAX_SAFE_INTEGER = 2**53 - 1
MAX_COLUMNS = 64
MAX_EXACT_CELLS = 1024
MAX_EXACT_BYTES = 160000


class ResultMetadataError(ValueError):
    """Fixed diagnostics never contain values, column names or source secrets."""


def _exact(value: Any) -> tuple[str, str] | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        if abs(value) <= MAX_SAFE_INTEGER:
            return None
        text = str(value)
        if len(text) > 256:
            raise ResultMetadataError("result_exact_value_too_large")
        return "integer", text
    if not isinstance(value, Decimal):
        return None
    if not value.is_finite():
        raise ResultMetadataError("result_number_invalid")
    if value == value.to_integral_value():
        if abs(value) <= MAX_SAFE_INTEGER:
            return None
    else:
        converted = float(value)
        if math.isfinite(converted) and Decimal(str(converted)) == value:
            return None
    # Bound expansion before formatting a scientific-notation Decimal.
    exponent = value.as_tuple().exponent
    if value.adjusted() > 255 or exponent < -255:
        raise ResultMetadataError("result_exact_value_too_large")
    text = format(value, "f")
    if len(text) > 256:
        raise ResultMetadataError("result_exact_value_too_large")
    return "decimal", text


def metadata_for(answer: Answer, *, source_id: str) -> dict[str, Any]:
    """Describe one completed bounded table without asserting source freshness.

    A finite sidecar records only cells that legacy numeric conversion would
    change. Refuse an oversized descriptor rather than silently dropping exact
    values. The caller separately enforces the whole serialized response cap.
    """
    if not re.fullmatch(r"[0-9a-f]{64}", source_id):
        raise ResultMetadataError("result_source_invalid")
    keys = _unique_keys(answer.columns)
    if len(keys) > MAX_COLUMNS or len(answer.rows) > DEFAULT_MAX_ROWS:
        raise ResultMetadataError("result_dimensions_exceeded")
    if len(set(keys)) != len(keys):
        raise ResultMetadataError("result_columns_ambiguous")
    exact: list[dict[str, Any]] = []
    for index, row in enumerate(answer.rows):
        if len(row) != len(keys):
            raise ResultMetadataError("result_row_invalid")
        for key, value in zip(keys, row, strict=True):
            selected = _exact(value)
            if selected is not None:
                kind, text = selected
                exact.append({"row": index, "column": key, "value": text, "kind": kind})
                if len(exact) > MAX_EXACT_CELLS:
                    raise ResultMetadataError("result_exact_cell_limit")
    metadata = {
        "version": 1,
        "source": {"id": source_id, "freshness_at": None},
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": None,
        "truncated": answer.truncated,
        "max_rows": DEFAULT_MAX_ROWS,
        "aggregation": "unknown",
        "column_units": dict.fromkeys(keys),
        "exact_values": exact,
    }
    if (
        len(json.dumps(metadata, ensure_ascii=False, allow_nan=False).encode())
        > MAX_EXACT_BYTES
    ):
        raise ResultMetadataError("result_metadata_too_large")
    return metadata
