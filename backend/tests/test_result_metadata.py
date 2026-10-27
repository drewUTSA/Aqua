"""Exact workspace cells survive legacy/JavaScript numeric conversion loss."""

from decimal import Decimal
import json

import pytest

from nl2sql.pipeline import Answer
from nl2sql.result_metadata import ResultMetadataError, metadata_for

SOURCE = "a" * 64


def test_workspace_metadata_preserves_only_loss_prone_values_without_invented_freshness():
    answer = Answer(
        "PRIVATE question must not enter metadata",
        "SELECT private_sql_must_not_enter_metadata",
        columns=["amount", "identifier", "ordinary", "money", "flag"],
        rows=[
            (
                Decimal("123456789012345.6789"),
                9007199254740993,
                7,
                Decimal("10.25"),
                True,
            )
        ],
        truncated=True,
    )
    saved = metadata_for(answer, source_id=SOURCE)
    assert saved["exact_values"] == [
        {
            "row": 0,
            "column": "amount",
            "value": "123456789012345.6789",
            "kind": "decimal",
        },
        {
            "row": 0,
            "column": "identifier",
            "value": "9007199254740993",
            "kind": "integer",
        },
    ]
    assert saved["source"] == {"id": SOURCE, "freshness_at": None}
    assert saved["filters"] is None and saved["aggregation"] == "unknown"
    assert saved["truncated"] and saved["max_rows"] == 1000
    assert all(value is None for value in saved["column_units"].values())
    assert "PRIVATE" not in json.dumps(saved)


def test_duplicate_column_keys_and_negative_unsafe_values_keep_the_correct_cell():
    saved = metadata_for(
        Answer(
            "Synthetic",
            "SELECT approved_columns",
            columns=["value", "value"],
            rows=[(-9007199254740993, Decimal("0.12345678901234567890"))],
        ),
        source_id=SOURCE,
    )
    assert [(cell["column"], cell["value"]) for cell in saved["exact_values"]] == [
        ("value", "-9007199254740993"),
        ("value_2", "0.12345678901234567890"),
    ]


@pytest.mark.parametrize(
    "value",
    [Decimal("NaN"), Decimal("Infinity"), Decimal("1e2000"), Decimal("1e-2000")],
)
def test_nonfinite_or_oversized_values_fail_closed(value):
    with pytest.raises(ResultMetadataError):
        metadata_for(
            Answer("Synthetic", "SELECT approved", columns=["value"], rows=[(value,)]),
            source_id=SOURCE,
        )


def test_exact_cell_budget_never_returns_an_incomplete_precision_descriptor():
    answer = Answer(
        "Synthetic",
        "SELECT approved",
        columns=["x", "y"],
        rows=[(9007199254740993, 9007199254740993)] * 600,
    )
    with pytest.raises(ResultMetadataError, match="exact_cell_limit"):
        metadata_for(answer, source_id=SOURCE)


def test_source_secrets_and_unbounded_dimensions_cannot_enter_metadata():
    with pytest.raises(ResultMetadataError, match="source_invalid"):
        metadata_for(
            Answer("Synthetic", "SELECT approved"),
            source_id="private connection must not escape",
        )
    with pytest.raises(ResultMetadataError, match="dimensions_exceeded"):
        metadata_for(
            Answer("Synthetic", "SELECT approved", columns=[str(n) for n in range(65)]),
            source_id=SOURCE,
        )


def test_generated_alias_collision_cannot_assign_precision_to_the_wrong_column():
    with pytest.raises(ResultMetadataError, match="columns_ambiguous"):
        metadata_for(
            Answer(
                "Synthetic",
                "SELECT approved",
                columns=["value", "value", "value_2"],
                rows=[(1, 2, 9007199254740993)],
            ),
            source_id=SOURCE,
        )
