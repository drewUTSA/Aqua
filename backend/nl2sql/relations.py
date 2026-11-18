"""Resolve physical tables and unambiguous direct projections in PostgreSQL."""

from __future__ import annotations

from typing import TYPE_CHECKING
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope

if TYPE_CHECKING:
    from nl2sql.schema import Column, Schema, Table


def identifier_name(value: exp.Expression | None, dialect: str) -> str:
    """PostgreSQL quoted identifiers are case sensitive; unquoted ones fold."""
    if value is None:
        return ""
    return (
        value.name
        if dialect == "postgres" and value.args.get("quoted")
        else value.name.lower()
    )


def physical_tables(statement: exp.Query) -> list[exp.Table]:
    """Return only actual relations; a CTE in an unrelated scope grants nothing."""
    tables = []
    for scope in traverse_scope(statement):
        for table in scope.tables:
            source = scope.sources.get(table.alias_or_name)
            if isinstance(source, Scope) and not table.db and not table.catalog:
                continue
            tables.append(table)
    return tables


def source_column(
    expression: exp.Column, tables: dict[str, Table | None]
) -> tuple[Table, Column] | None:
    qualifier = identifier_name(expression.args.get("table"), "postgres")
    candidates = [tables.get(qualifier)] if qualifier else list(tables.values())
    if not candidates or any(table is None for table in candidates):
        return None
    name = identifier_name(expression.this, "postgres")
    matches = [(t, c) for t in candidates for c in t.columns if c.name == name]
    return matches[0] if len(matches) == 1 else None


def projected_columns(
    sql: str, width: int, schema: Schema
) -> list[tuple[Table, Column] | None]:
    """A direct column's provenance by output position. Unproved outputs stay literal."""
    unknown = [None] * width
    try:
        query = parse_one(sql, read="postgres")
    except SqlglotError:
        return unknown
    if (
        not isinstance(query, exp.Select)
        or len(query.expressions) != width
        or query.args.get("with_")
        or query.find(exp.Subquery)
        or len(list(query.find_all(exp.Select))) != 1
    ):
        return unknown
    relations = [query.args.get("from_").this] if query.args.get("from_") else []
    relations.extend(join.this for join in query.args.get("joins", ()))
    tables = {}
    for relation in relations:
        if not isinstance(relation, exp.Table) or not isinstance(
            relation.this, exp.Identifier
        ):
            return unknown
        alias = relation.args.get("alias")
        if (
            relation.catalog
            or identifier_name(relation.args.get("db"), "postgres")
            not in ("", "public")
            or (alias and alias.args.get("columns"))
        ):
            return unknown
        name = identifier_name(relation.this, "postgres")
        key = identifier_name(alias.this, "postgres") if alias else name
        if name not in schema.tables or key in tables:
            return unknown
        tables[key] = schema.tables[name]
    result = []
    for expression in query.expressions:
        column = expression.unalias().unnest()
        result.append(
            source_column(column, tables) if isinstance(column, exp.Column) else None
        )
    return result
