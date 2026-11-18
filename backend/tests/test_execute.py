"""Tests for nl2sql/execute.py.

The row-limit and unit tests need no database. The test_real_* tests run
against disposable fixtures as nl2sql_reader; ordinary DATABASE_URL is ignored.
"""

import time

import psycopg
import pytest

from nl2sql import execute as execute_module
from nl2sql.config import Settings, load_settings
from nl2sql.control import Budget, CURRENT, ExecutionStopped
from nl2sql.db import DatabaseError
from nl2sql.execute import DEFAULT_MAX_ROWS, QueryError, execute, limit_rows
from nl2sql.validate import UnsafeQueryError, validate_sql

# ---- row limit (moved here from test_validate.py) ----


def limited(sql: str, dialect: str = "postgres", max_rows: int = 1000) -> str:
    """Validate, apply the row limit, and return the SQL that would run."""
    return limit_rows(validate_sql(sql, dialect=dialect), max_rows).sql(dialect=dialect)


@pytest.mark.parametrize(
    ("dialect", "sql", "expected"),
    [
        ("postgres", "SELECT title FROM film", "SELECT title FROM film LIMIT 1000"),
        (
            "postgres",
            "SELECT title FROM film LIMIT 5",
            "SELECT title FROM film LIMIT 5",
        ),
        (
            "postgres",
            "SELECT title FROM film LIMIT 5000",
            "SELECT title FROM film LIMIT 1000",
        ),
        (
            "postgres",
            "SELECT title FROM film ORDER BY title LIMIT 5000",
            "SELECT title FROM film ORDER BY title LIMIT 1000",
        ),
        (
            "postgres",
            "SELECT title FROM film LIMIT 5000 OFFSET 20",
            "SELECT title FROM film LIMIT 1000 OFFSET 20",
        ),
        ("postgres", "SELECT 1 UNION SELECT 2", "SELECT 1 UNION SELECT 2 LIMIT 1000"),
        # The inner limit is left alone; only the outer query is capped.
        (
            "postgres",
            "SELECT * FROM (SELECT title FROM film LIMIT 2000) AS t",
            "SELECT * FROM (SELECT title FROM film LIMIT 2000) AS t LIMIT 1000",
        ),
        (
            "postgres",
            "SELECT title FROM film FETCH FIRST 5000 ROWS ONLY",
            "SELECT title FROM film LIMIT 1000",
        ),
        (
            "postgres",
            "SELECT title FROM film FETCH FIRST 3 ROWS ONLY",
            "SELECT title FROM film LIMIT 3",
        ),
        (
            "postgres",
            "SELECT title FROM film LIMIT ALL",
            "SELECT title FROM film LIMIT 1000",
        ),
        # MySQL's "LIMIT offset, count" keeps its meaning.
        (
            "mysql",
            "SELECT title FROM film LIMIT 10, 5",
            "SELECT title FROM film LIMIT 5 OFFSET 10",
        ),
    ],
)
def test_row_limit(dialect: str, sql: str, expected: str) -> None:
    assert limited(sql, dialect=dialect) == expected


def test_custom_max_rows() -> None:
    assert (
        limited("SELECT title FROM film", max_rows=50)
        == "SELECT title FROM film LIMIT 50"
    )


def test_default_max_rows_is_used() -> None:
    tree = limit_rows(validate_sql("SELECT title FROM film"))
    assert tree.sql() == f"SELECT title FROM film LIMIT {DEFAULT_MAX_ROWS}"


def test_expression_limit_is_rejected() -> None:
    with pytest.raises(UnsafeQueryError, match="whole number"):
        limited("SELECT title FROM film LIMIT 1+1")


def test_original_query_is_not_changed() -> None:
    """The caller may still want to log exactly what the model wrote."""
    tree = validate_sql("SELECT title FROM film LIMIT 5000")
    limit_rows(tree)
    assert tree.sql() == "SELECT title FROM film LIMIT 5000"


@pytest.mark.parametrize("direction", ["FIRST", "NEXT"])
def test_omitted_fetch_only_count_defaults_to_one(direction):
    assert limited(f"SELECT title FROM film FETCH {direction} ROW ONLY") == (
        "SELECT title FROM film LIMIT 1"
    )


def test_ties_cannot_be_hard_capped_by_replacing_the_fetch_clause():
    with pytest.raises(UnsafeQueryError, match="bounded cursor"):
        limited("SELECT title FROM film ORDER BY length FETCH FIRST 2 ROWS WITH TIES")


@pytest.mark.parametrize(
    "suffix", ["FETCH FIRST (1 + 1) ROWS WITH TIES", "FETCH FIRST 2 PERCENT ROWS ONLY"]
)
def test_unsupported_fetch_counts_are_rejected_before_contacting_the_database(suffix):
    with pytest.raises(UnsafeQueryError):
        execute(
            validate_sql(f"SELECT title FROM film ORDER BY length {suffix}"), Settings()
        )


# ---- execute, with a stand-in connection ----


class FakeCursor:
    def __init__(self, columns: list[str], rows: list[tuple]):
        self.description = [type("Column", (), {"name": name})() for name in columns]
        self._rows = rows

    def fetchall(self) -> list[tuple]:
        return self._rows


class FakeConnection:
    """Records the SQL it is given; returns canned rows or raises."""

    def __init__(self, columns=(), rows=(), error: Exception | None = None):
        self.executed: list[str] = []
        self._cursor = FakeCursor(list(columns), list(rows))
        self._error = error

    def execute(self, sql: str) -> FakeCursor:
        self.executed.append(sql)
        if self._error is not None:
            raise self._error
        return self._cursor

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def use_fake(monkeypatch: pytest.MonkeyPatch, conn: FakeConnection) -> None:
    monkeypatch.setattr(execute_module, "connect", lambda settings: conn)


SETTINGS = Settings(database_url="postgresql://u:p@db.example.test/tsdb")


@pytest.mark.parametrize("failure", [None, "expired", "fetch_error"])
def test_ties_use_one_bounded_forward_fetch_and_close_the_cursor(monkeypatch, failure):
    class Portal(FakeCursor):
        def __enter__(self):
            self.closed = False
            return self

        def __exit__(self, *exc):
            self.closed = True

        def execute(self, sql):
            self.statement = sql
            if failure == "expired":
                budget.deadline = time.monotonic() - 1

        def fetchmany(self, n):
            self.requested = n
            if failure == "fetch_error":
                raise psycopg.errors.QueryCanceled("private text from the fixture")
            return self._rows[:n]

        def fetchall(self):
            pytest.fail("the driver must never request the full tie group")

    class Connection(FakeConnection):
        def execute(self, sql, *params):
            return super().execute(sql)

        def cursor(self, name, *, scrollable, withhold):
            assert name and not scrollable and not withhold
            return portal

    portal = Portal(["title"], [(str(i),) for i in range(6)])
    conn = Connection()
    use_fake(monkeypatch, conn)
    query = validate_sql(
        "SELECT title FROM film ORDER BY length FETCH FIRST ROW WITH TIES"
    )
    budget = Budget(time.monotonic() + 30, lambda _: None)
    token = CURRENT.set(budget)
    try:
        if failure == "expired":
            with pytest.raises(ExecutionStopped, match="analysis_expired"):
                execute(query, SETTINGS, max_rows=3)
            assert not hasattr(portal, "requested")
        elif failure == "fetch_error":
            with pytest.raises(QueryError) as caught:
                execute(query, SETTINGS, max_rows=3)
            assert caught.value.code == "timeout" and "private text" not in str(
                caught.value
            )
        else:
            result = execute(query, SETTINGS, max_rows=3)
            assert portal.requested == 4
            assert "WITH TIES" in result.sql and result.sql == portal.statement
            assert result.columns == ["title"] and result.rows == [
                ("0",),
                ("1",),
                ("2",),
            ]
            assert result.truncated
    finally:
        CURRENT.reset(token)
    assert portal.closed


@pytest.mark.parametrize("cap", [-1, False, 1.5])
def test_invalid_cursor_cap_is_rejected_before_connecting(cap):
    query = validate_sql(
        "SELECT title FROM film ORDER BY length FETCH FIRST ROW WITH TIES"
    )
    with pytest.raises(ValueError, match="non-negative integer"):
        execute(query, Settings(), max_rows=cap)


def test_ties_are_never_rendered_using_an_unqualified_dialect():
    query = validate_sql(
        "SELECT title FROM film ORDER BY length FETCH FIRST ROW WITH TIES"
    )
    with pytest.raises(UnsafeQueryError, match="requires PostgreSQL"):
        execute(query, Settings(), dialect="sqlite")


def test_asks_for_one_extra_row_and_reports_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = FakeConnection(columns=["title"], rows=[("A",), ("B",)])
    use_fake(monkeypatch, conn)

    result = execute(validate_sql("SELECT title FROM film"), SETTINGS, max_rows=10)

    assert conn.executed == [
        "SET LOCAL search_path = pg_catalog",
        "SELECT title FROM public.film LIMIT 11",
    ]
    assert result.columns == ["title"]
    assert result.rows == [("A",), ("B",)]
    assert result.truncated is False
    assert result.sql == "SELECT title FROM public.film LIMIT 10"  # what the user sees


def test_extra_row_means_truncated(monkeypatch: pytest.MonkeyPatch) -> None:
    conn = FakeConnection(columns=["n"], rows=[(i,) for i in range(4)])
    use_fake(monkeypatch, conn)

    result = execute(
        validate_sql("SELECT film_id AS n FROM film"), SETTINGS, max_rows=3
    )

    assert result.rows == [(0,), (1,), (2,)]
    assert result.truncated is True


def test_database_rejection_becomes_query_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = psycopg.errors.UndefinedColumn(
        'column "nope" does not exist\nLINE 1: SELECT nope ...'
    )
    use_fake(monkeypatch, FakeConnection(error=error))

    with pytest.raises(QueryError, match="column does not exist") as info:
        execute(validate_sql("SELECT nope FROM film"), SETTINGS)
    assert "LINE 1" not in str(info.value)  # first line only


def test_connection_errors_are_not_disguised(monkeypatch: pytest.MonkeyPatch) -> None:
    def failing_connect(settings):
        raise DatabaseError("Could not connect to the database: timeout")

    monkeypatch.setattr(execute_module, "connect", failing_connect)
    with pytest.raises(DatabaseError):
        execute(validate_sql("SELECT 1"), SETTINGS)


def test_raw_strings_are_refused() -> None:
    """Only validate_sql() output may reach the database."""
    with pytest.raises(TypeError, match="validate_sql"):
        execute("SELECT * FROM film", SETTINGS)  # type: ignore[arg-type]


# ---- execute against the real database ----

REAL = load_settings()

# A table and its key on each database, for the tests below.
TABLE = {"bank": ("trans", "trans_id"), "pagila": ("film", "film_id")}


@pytest.mark.parametrize(
    ("ending", "cap", "expected", "truncated"),
    [
        ("FETCH FIRST ROW ONLY", 5, [1], False),
        ("FETCH FIRST ROW WITH TIES", 5, [1, 1], False),
        ("OFFSET 1 ROW FETCH NEXT 2 ROWS WITH TIES", 5, [1, 2, 2], False),
        ("FETCH FIRST 3 ROWS WITH TIES", 4, [1, 1, 2, 2], False),
        ("FETCH FIRST 3 ROWS WITH TIES", 3, [1, 1, 2], True),
        ("FETCH FIRST 100 ROWS WITH TIES", 2, [1, 1], True),
        ("FETCH FIRST 0 ROWS WITH TIES", 3, [], False),
        ("FETCH FIRST ROW WITH TIES", 0, [], True),
    ],
)
def test_real_fetch_membership_order_projection_and_truncation(
    live_database, ending, cap, expected, truncated
):
    # Repeated output values make order within ties immaterial, while the
    # distinct sort key remains absent from the projection the employee sees.
    sql = (
        "SELECT label FROM (VALUES (2, 10), (1, 20), (3, 5), (2, 10), (1, 20)) "
        f"AS sample(label, score) ORDER BY score DESC {ending}"
    )
    result = execute(validate_sql(sql, allowed_tables=set()), REAL, max_rows=cap)
    assert result.columns == ["label"] and result.rows == [(n,) for n in expected]
    assert result.truncated is truncated
    replay = execute(validate_sql(result.sql, allowed_tables=set()), REAL, max_rows=cap)
    assert replay == result


def test_real_query_returns_rows(live_database: str) -> None:
    table, _ = TABLE[live_database]
    result = execute(validate_sql(f"SELECT count(*) AS n FROM {table}"), REAL)
    assert result.columns == ["n"]
    assert result.rows[0][0] > 0
    assert result.truncated is False


def test_real_truncation(live_database: str) -> None:
    table, key = TABLE[live_database]
    result = execute(
        validate_sql(f"SELECT {key} FROM {table} ORDER BY {key}"), REAL, max_rows=10
    )
    assert len(result.rows) == 10
    assert result.truncated is True


def test_real_smaller_limit_is_kept(live_database: str) -> None:
    table, key = TABLE[live_database]
    result = execute(
        validate_sql(f"SELECT {key} FROM {table} LIMIT 5"), REAL, max_rows=10
    )
    assert len(result.rows) == 5
    assert result.truncated is False


def test_real_unknown_column_is_a_query_error(live_database: str) -> None:
    table, _ = TABLE[live_database]
    with pytest.raises(QueryError, match="does not exist"):
        execute(validate_sql(f"SELECT no_such_column FROM {table}"), REAL)


def test_real_statement_timeout_is_a_query_error(live_database: str) -> None:
    """The fixture role cancels an expensive query after 100 ms.

    This checks error propagation without spending the production 10 seconds.
    """
    table, _ = TABLE[live_database]
    joined = " CROSS JOIN ".join(f"{table} {alias}" for alias in "abcd")
    with pytest.raises(QueryError, match="statement timeout"):
        execute(validate_sql(f"SELECT count(*) FROM {joined}"), REAL)
