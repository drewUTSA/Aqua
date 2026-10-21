"""P01 red cases: synthetic canaries must never cross data boundaries."""

from unittest.mock import Mock

import psycopg
import pytest

from nl2sql.cache import cache_key
from nl2sql.config import Settings
from nl2sql.execute import QueryError, execute
from nl2sql.pipeline import Context, build_context
from nl2sql.schema import Column, Schema, Table, load_schema
from nl2sql.validate import validate_sql

CANARY = "PRIVATE_SYNTHETIC_CANARY_927"
SCHEMA = Schema(
    tables={"film": Table("film", (Column("title", "text", True),), (), frozenset())}
)


@pytest.mark.parametrize(
    "left,right",
    [
        ('Find code "AbC"', 'Find code "abc"'),
        ('Find name "A  B"', 'Find name "A B"'),
        ("Find suffix abc!", "Find suffix abc"),
    ],
)
def test_cache_does_not_merge_different_literal_meanings(left, right):
    assert cache_key(left, "model") != cache_key(right, "model")


def test_cache_parts_cannot_collide_at_separator():
    assert cache_key("q", "a\x1fb", "c") != cache_key("q", "a", "b\x1fc")


def test_query_error_never_echoes_database_values(monkeypatch):
    conn = Mock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    conn.execute.side_effect = psycopg.errors.InvalidTextRepresentation(CANARY)
    monkeypatch.setattr("nl2sql.execute.connect", lambda settings: conn)
    with pytest.raises(QueryError) as caught:
        execute(validate_sql("SELECT 1"), Settings())
    assert CANARY not in str(caught.value)


def test_retrieval_authorization_failure_does_not_fall_back():
    retriever = Mock()
    retriever.select.side_effect = PermissionError(CANARY)
    with pytest.raises(RuntimeError):
        build_context("q", SCHEMA, retriever)


def test_retriever_cannot_supply_arbitrary_provider_schema():
    retriever = Mock()
    retriever.select.return_value = Context(CANARY, tables=("film",))
    context, used = build_context("q", SCHEMA, retriever)
    assert used
    assert CANARY not in context.schema_text
    assert context.schema_text == SCHEMA.to_prompt(["film"])


def test_schema_has_no_row_samples_or_live_comments(on_pagila):
    from nl2sql.config import load_settings
    from nl2sql.db import connect

    with connect(load_settings()) as conn:
        schema = load_schema(conn)
    prompt = schema.to_prompt()
    assert CANARY not in prompt
    assert all(
        c.values == ()
        for name in ("actor", "customer")
        for c in schema.tables[name].columns
    )
