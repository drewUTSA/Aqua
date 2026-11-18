"""Prove a small unit vocabulary from SQL expressions and authorized schema comments."""

import re
from sqlglot import exp, parse_one
from sqlglot.errors import SqlglotError
from nl2sql.pipeline import Answer
from nl2sql.relations import identifier_name, source_column
from nl2sql.schema import Schema

_CURRENCY = re.compile(r"\(([A-Z]{3})\)")
_MONEY = re.compile(r"\b(?:amount|balance|price|salary|cost|revenue|payment)\b", re.I)


def units_for(answer: Answer, schema: Schema | None) -> list[str | None]:
    """Unknown lineage stays unknown; names alone cannot establish financial units.

    COUNT has a count unit. Direct columns and unit-preserving aggregates may
    inherit a currency explicitly documented by their source column/table.
    Joins resolve aliases, but CTEs, arbitrary arithmetic and casts are unknown.
    """
    unknown = [None] * len(answer.columns)
    if schema is None:
        return unknown
    try:
        query = parse_one(answer.sql, read="postgres")
    except SqlglotError:
        return unknown
    if (
        not isinstance(query, exp.Select)
        or query.args.get("with_")
        or any(query.find_all(exp.Subquery))
    ):
        return unknown
    if len(query.expressions) != len(answer.columns):
        return unknown
    tables = {}
    for table in query.find_all(exp.Table):
        alias = table.args.get("alias")
        key = identifier_name(alias.this if alias else table.this, "postgres")
        tables[key] = schema.tables.get(identifier_name(table.this, "postgres"))

    def unit(expression: exp.Expression) -> str | None:
        if isinstance(
            expression, (exp.Alias, exp.Paren, exp.Sum, exp.Avg, exp.Min, exp.Max)
        ):
            return unit(expression.this)
        if isinstance(expression, exp.Count):
            return "count"
        if not isinstance(expression, exp.Column):
            return None
        found = source_column(expression, tables)
        if found is None:
            return None
        table, column = found
        currencies = set(_CURRENCY.findall(column.comment))
        if not currencies and _MONEY.search(column.comment):
            currencies = set(_CURRENCY.findall(table.comment))
        return next(iter(currencies)) if len(currencies) == 1 else None

    return [unit(expression) for expression in query.expressions]
