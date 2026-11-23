"""Run validated SQL against the database and return the rows.

Takes the parsed query that validate_sql() returns, not a SQL string, so
nothing reaches the database without going through the validator first.
Every query is capped at a row limit, and the result says whether rows
were cut off. The connection comes from db.py, so it is the read-only
role in a read-only transaction, and the role's statement_timeout stops
any query that runs too long.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import psycopg
from sqlglot import exp

from nl2sql.config import Settings
from nl2sql.db import connect
from nl2sql.errors import diagnostic, query_code
from nl2sql.relations import physical_tables
from nl2sql.validate import UnsafeQueryError
from nl2sql.control import CURRENT, remaining

# Most rows any query may return. Enough for any table a person would
# read in the panel; stops "list all customers" pulling a whole table.
DEFAULT_MAX_ROWS = 1000


class QueryError(RuntimeError):
    """The database rejected or could not finish a validated query.

    Only a closed diagnostic code crosses this boundary. Never retain raw
    database messages: casts, constraints and functions may echo private values.
    """

    def __init__(self, code: str = "query_failed") -> None:
        self.code = (
            code
            if code in {"invalid_column", "invalid_query", "timeout", "access_denied"}
            else "query_failed"
        )
        self.fixable = diagnostic(self.code).fixable
        super().__init__(diagnostic(self.code).message)


@dataclass(frozen=True)
class QueryResult:
    """What a query returned.

    `sql` is the analytical statement shown to the user. For FETCH WITH TIES
    it preserves the native cutoff and ordering. Aqua additionally limits
    rows fetched from the cursor. An external SQL client sets its own cap.
    `truncated` is True when there were more rows than max_rows.
    """

    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    truncated: bool
    # A native first-row cutoff with ties proves peer membership even when the
    # sort value is absent from the displayed columns.
    first_place_peers: bool = False


def _exclude_unknown_score(query: exp.Select, requested: str) -> bool:
    score = query.args["order"].expressions[0].this
    if isinstance(score, exp.Column) and not score.table:
        fields = [
            f.unalias() for f in query.expressions if f.alias_or_name == score.name
        ]
        if len(fields) > 1:
            return False
        if fields:
            score = fields[0]
    aggregate = isinstance(score, (exp.Sum, exp.Avg, exp.Min, exp.Max))
    column = score.this if aggregate else score
    if not isinstance(column, exp.Column):
        return False
    terms = set(column.name.split("_"))
    if requested not in terms:
        generic_numeric = requested in {"score", "value"} and (
            isinstance(score, (exp.Sum, exp.Avg))
            or bool(
                terms
                & {
                    "amount",
                    "total",
                    "sum",
                    "score",
                    "value",
                    "balance",
                    "rate",
                    "price",
                    "cost",
                    "weight",
                    "duration",
                }
            )
        )
        if not generic_numeric and not (
            requested in {"sum", "total"} and isinstance(score, exp.Sum)
        ):
            return False
    group = query.args.get("group")
    if group and (
        not aggregate or any(v for k, v in group.args.items() if k != "expressions")
    ):
        return False
    if not aggregate and any(
        isinstance(n, exp.AggFunc) for f in query.expressions for n in f.walk()
    ):
        return False
    known = exp.Not(this=exp.Is(this=score.copy(), expression=exp.Null()))
    if aggregate:
        query.having(known, append=True, copy=False)
    else:
        query.where(known, append=True, copy=False)
    return True


def include_cutoff_peers(
    query: exp.Query, rows: int | None, *, known_measure: str | None = None
) -> str | None:
    """Preserve peers for a simple PostgreSQL ranking with an explicit row cutoff.

    A secondary sort key can determine membership, so preserve its original
    order and cutoff. An explicit known-value request can still exclude NULLs
    from the primary measure. Nested cutoffs, windows and offsets are delegated.
    """
    if not isinstance(query, exp.Select):
        return None
    order = query.args.get("order")
    if not order or not order.expressions or query.args.get("offset"):
        return None
    secondary = len(order.expressions) > 1
    if secondary and not known_measure:
        return None
    limit = query.args.get("limit")
    if not isinstance(limit, (exp.Limit, exp.Fetch)):
        return None
    count, already_inclusive = _requested_limit(query)
    if count is None or (rows is not None and count != rows):
        return None
    if (already_inclusive or rows is None) and not known_measure:
        return None
    for node in query.walk():
        if isinstance(node, (exp.Window, exp.Offset)) or (
            isinstance(node, (exp.Fetch, exp.Limit)) and node is not limit
        ):
            return None
    rewritten = query.copy()
    filtered = bool(known_measure and _exclude_unknown_score(rewritten, known_measure))
    if already_inclusive or rows is None or secondary:
        return rewritten.sql(dialect="postgres") if filtered else None
    rewritten.set(
        "limit",
        exp.Fetch(
            direction="FIRST",
            count=exp.Literal.number(rows),
            limit_options=exp.LimitOptions(rows=True, with_ties=True),
        ),
    )
    return rewritten.sql(dialect="postgres")


def _requested_limit(query: exp.Query) -> tuple[int | None, bool]:
    """Return the outer row count and whether PostgreSQL must include its peers."""
    current = query.args.get("limit")
    if current is None:
        return None, False
    ties = False
    if isinstance(current, exp.Fetch):
        options = current.args.get("limit_options")
        if options and options.args.get("percent"):
            raise UnsafeQueryError("FETCH must specify a row count.")
        ties = bool(options and options.args.get("with_ties"))
        requested = current.args.get("count")
        if requested is None:
            return 1, ties  # FETCH FIRST ROW defaults to one under PostgreSQL.
    else:
        requested = current.expression  # None for LIMIT ALL
    if requested is None:
        return None, False
    if not (isinstance(requested, exp.Literal) and requested.is_int):
        raise UnsafeQueryError("LIMIT must be a whole number.")
    return int(requested.this), ties


def limit_rows(query: exp.Query, max_rows: int = DEFAULT_MAX_ROWS) -> exp.Query:
    """Cap the outer row limit of a query whose result allows a literal LIMIT."""
    requested, ties = _requested_limit(query)
    if ties:
        raise UnsafeQueryError("FETCH WITH TIES requires bounded cursor execution.")
    return query.limit(max_rows if requested is None else min(requested, max_rows))


def _set_remaining_timeout(conn: psycopg.Connection) -> None:
    milliseconds = max(1, int(remaining(10) * 1000))
    conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(milliseconds),))


def execute(
    query: exp.Query,
    settings: Settings,
    max_rows: int = DEFAULT_MAX_ROWS,
    dialect: str = "postgres",
) -> QueryResult:
    """Run a validated query and return its columns and rows.

    Asks the database for one row more than max_rows: if that extra row
    comes back, the result was cut off. Raises QueryError if the database
    rejects the query and db.DatabaseError if it cannot be reached.
    """
    if not isinstance(query, exp.Query):
        raise TypeError(
            "execute() takes the parsed query from validate_sql(), not a string."
        )
    if type(max_rows) is not int or max_rows < 0:
        raise ValueError("max_rows must be a non-negative integer.")

    query = query.copy()
    if dialect == "postgres":
        # Legacy validator callers can omit a table allowlist. Preserve public
        # table resolution for them without putting public functions in scope.
        for table in physical_tables(query):
            if isinstance(table.this, exp.Identifier) and not table.db:
                table.set("db", exp.to_identifier("public"))
    requested, ties = _requested_limit(query)
    if ties:
        if dialect != "postgres":
            raise UnsafeQueryError("FETCH WITH TIES requires PostgreSQL.")
        probe_sql = shown_sql = query.sql(dialect=dialect)
    else:
        probe_sql = limit_rows(query, max_rows + 1).sql(dialect=dialect)
        shown_sql = limit_rows(query, max_rows).sql(dialect=dialect)
    with connect(settings) as conn:
        try:
            # Only resolve built-ins; public functions can overload safe names.
            # The validator already qualifies approved tables with public.
            # This is transaction-local, never a change to roles or hosted storage.
            conn.execute("SET LOCAL search_path = pg_catalog")
            budget = CURRENT.get()
            if budget:
                _set_remaining_timeout(conn)
                conn.execute("SET LOCAL lock_timeout = '1s'")
            if ties:
                # The peer group at the cutoff can be arbitrarily large. A
                # server cursor keeps the original ORDER BY and OFFSET while
                # transferring only the bounded prefix, even when tied fields
                # are absent from the employee's requested output columns.
                with conn.cursor(
                    name="aqua_tied_rows", scrollable=False, withhold=False
                ) as cursor:
                    cursor.execute(probe_sql)
                    if budget:
                        _set_remaining_timeout(conn)
                    rows = cursor.fetchmany(max_rows + 1)
                    columns = [column.name for column in cursor.description or []]
                    if budget:
                        budget.remaining()
            else:
                cursor = conn.execute(probe_sql)
                rows = cursor.fetchall()
                columns = [column.name for column in cursor.description or []]
        except psycopg.Error as exc:
            raise QueryError(query_code(exc.sqlstate)) from None

    return QueryResult(
        sql=shown_sql,
        columns=columns,
        rows=rows[:max_rows],
        truncated=len(rows) > max_rows,
        first_place_peers=bool(
            ties
            and requested == 1
            and not query.args.get("offset")
            and query.args.get("order")
            and len(query.args["order"].expressions) == 1
        ),
    )
