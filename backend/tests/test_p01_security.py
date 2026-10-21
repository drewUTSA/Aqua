"""Paired attack/defense checks; all payloads and accounts are synthetic."""

from dataclasses import replace
from unittest.mock import Mock

import httpx
import psycopg
import pytest

from nl2sql.cache import AnswerCache, scoped_cache_key
from nl2sql.cache_scope import CacheScope
from nl2sql.config import Settings, load_settings
from nl2sql.db import connect
from nl2sql.errors import ContextDenied
from nl2sql.execute import QueryError, execute
from nl2sql.generate import Attempt, build_prompt
from nl2sql.llm import LLMError, complete
from nl2sql.pipeline import Answer, Context, build_context
from nl2sql.response import to_response
from nl2sql.schema import Column, Schema, Table, load_schema
from nl2sql.validate import UnsafeQueryError, validate_sql

CANARY = "PRIVATE_SYNTHETIC_CANARY_927"
SCHEMA = Schema(
    {"film": Table("film", (Column("title", "text", True),), (), frozenset())}
)
SCOPE = CacheScope("google:fixture-a", "dataset", "grant-v1", "schema-v1")


@pytest.mark.parametrize(
    "field",
    [
        "principal",
        "dataset",
        "authorization_revision",
        "schema_revision",
        "context_revision",
        "policy_version",
    ],
)
def test_each_cache_boundary_partitions_identical_questions(field):
    assert scoped_cache_key("q", SCOPE) != scoped_cache_key(
        "q", replace(SCOPE, **{field: "different"})
    )


def test_cache_expiration_is_exact_and_storage_is_bounded():
    now = [0]
    cache = AnswerCache(60, max_entries=2, clock=lambda: now[0])
    answer = Answer("q", "SELECT 1", rows=[(1,)])
    cache.put("a", answer)
    now[0] = 60
    assert cache.get("a") is None
    cache.put("huge", replace(answer, rows=[("x" * (1024 * 1024 + 1),)]))
    assert cache.get("huge") is None
    for key in ("b", "c", "d"):
        cache.put(key, answer)
    assert cache.get("b") is None and cache.get("d") is answer
    assert cache._bytes >= 0 and len(cache._sizes) == 2


def test_repair_prompt_and_response_refuse_arbitrary_diagnostics():
    assert CANARY not in build_prompt(
        "q", SCHEMA.to_prompt(), previous=Attempt("SELECT 1", CANARY)
    )
    body = to_response(Answer("q", "SELECT 1", error=CANARY, error_code="query_failed"))
    assert CANARY not in str(body)


@pytest.mark.parametrize(
    "error",
    [
        PermissionError(CANARY),
        psycopg.errors.InsufficientPrivilege(CANARY),
        RuntimeError(CANARY),
    ],
)
def test_denied_or_unknown_retrieval_never_widens_and_logs_no_payload(error, caplog):
    retriever = Mock()
    retriever.select.side_effect = error
    with pytest.raises(ContextDenied):
        build_context("q", SCHEMA, retriever)
    assert CANARY not in caplog.text
    assert "retrieval_denied action=stop" in caplog.text


def test_forged_retrieval_relation_is_refused():
    retriever = Mock()
    retriever.select.return_value = Context("whatever", tables=("private_accounts",))
    with pytest.raises(ContextDenied):
        build_context("q", SCHEMA, retriever)


def test_provider_http_body_is_not_a_diagnostic():
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(403, text=CANARY))
    )
    with pytest.raises(LLMError) as caught:
        complete("synthetic", Settings(llm_fallback=False), client=client)
    assert CANARY not in str(caught.value)


@pytest.mark.parametrize(
    "state,code,fixable",
    [
        ("42703", "invalid_column", True),
        ("57014", "timeout", False),
        ("42501", "access_denied", False),
        ("P0001", "query_failed", False),
    ],
)
def test_sqlstate_controls_repairs_not_localized_error_values(
    monkeypatch, state, code, fixable
):
    error = psycopg.errors.lookup(state)(CANARY)
    conn = Mock()
    conn.__enter__ = Mock(return_value=conn)
    conn.__exit__ = Mock(return_value=False)
    conn.execute.side_effect = error
    monkeypatch.setattr("nl2sql.execute.connect", lambda _: conn)
    with pytest.raises(QueryError) as caught:
        execute(validate_sql("SELECT 1"), Settings())
    assert (caught.value.code, caught.value.fixable) == (code, fixable)
    assert CANARY not in str(caught.value)


def test_catalog_loading_is_constant_query_count_without_row_sampling(live_database):
    class CountingConnection:
        def __init__(self, conn):
            self.conn, self.queries = conn, []

        def execute(self, statement, *args):
            self.queries.append(statement)
            return self.conn.execute(statement, *args)

    with connect(load_settings()) as conn:
        wrapped = CountingConnection(conn)
        schema = load_schema(wrapped)
    assert len(wrapped.queries) == 3
    assert all(
        "SELECT DISTINCT" not in q
        and "obj_description" not in q
        and "col_description" not in q
        for q in wrapped.queries
    )
    assert schema.tables


def test_real_restricted_role_denies_private_schema_and_preserves_rows(live_database):
    table, key = (
        ("film", "film_id") if live_database == "pagila" else ("trans", "trans_id")
    )
    settings = load_settings()
    with connect(settings) as conn:
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            conn.execute("SELECT * FROM aqua_private.accounts")
    query = validate_sql(
        f"SELECT {key} FROM {table} ORDER BY {key} LIMIT 5", allowed_tables={table}
    )
    result = execute(query, settings)
    assert result.rows == [(n,) for n in range(1, 6)]


def test_qualified_query_is_not_redirected_by_search_path(live_database):
    table = "film" if live_database == "pagila" else "trans"
    query = validate_sql(f"SELECT count(*) FROM {table}", allowed_tables={table})
    with connect(load_settings()) as conn:
        conn.execute("SET LOCAL search_path = shadow, public")
        assert conn.execute(f"SELECT count(*) FROM {table}").fetchone() == (1,)
        assert conn.execute(query.sql(dialect="postgres")).fetchone() == (1000,)


def test_oversized_query_is_refused_before_parser():
    with pytest.raises(UnsafeQueryError, match="query size"):
        validate_sql("SELECT '" + "x" * 32768 + "'")


def test_public_overload_cannot_impersonate_approved_builtin(live_database):
    settings = load_settings()
    with connect(settings) as conn:
        assert conn.execute("SELECT lower(42)").fetchone() == (CANARY,)
    with pytest.raises(QueryError) as caught:
        execute(validate_sql("SELECT lower(42)"), settings)
    assert caught.value.code == "invalid_query"
    assert CANARY not in str(caught.value)
    assert execute(validate_sql("SELECT lower('SAFE')"), settings).rows == [("safe",)]


def test_parser_fallback_does_not_log_query_contents(caplog):
    with pytest.raises(UnsafeQueryError):
        validate_sql("GRANT SELECT ON " + CANARY + " TO somebody")
    assert CANARY not in caplog.text


def test_reference_results_survive_relation_qualification(live_database):
    table, key = (
        ("film", "film_id") if live_database == "pagila" else ("trans", "trans_id")
    )
    queries = [
        f"SELECT count(*) FROM {table}",
        f"WITH X AS (SELECT {key} AS n FROM {table} WHERE {key} < 10) SELECT sum(n) FROM x",
        f"SELECT min({key}), max({key}), sum({key}) FROM {table}",
    ]
    expected = [[(1000,)], [(45,)], [(1, 1000, 500500)]]
    settings = load_settings()
    for text, rows in zip(queries, expected):
        with connect(settings) as conn:
            assert conn.execute(text).fetchall() == rows
        assert (
            execute(validate_sql(text, allowed_tables={table}), settings).rows == rows
        )
