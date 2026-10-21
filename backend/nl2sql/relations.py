"""Resolve physical tables by lexical SQL scope, not a global set of CTE names."""

from sqlglot import exp
from sqlglot.optimizer.scope import Scope, traverse_scope


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
