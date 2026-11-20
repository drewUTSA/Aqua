"""Resolve unambiguous counts of records in the two reviewed demo catalogs."""

import re

from nl2sql.metadata_policy import BANK_TABLES, PAGILA_TABLES
from nl2sql.schema import Schema

_BANK = {
    "transactions": "trans",
    "accounts": "account",
    "bank accounts": "account",
    "clients": "client",
    "customers": "client",
    "credit cards": "card",
    "loans": "loan",
    "standing orders": "order",
    "districts": "district",
}
_PAGILA = {
    "actors": "actor",
    "customers": "customer",
    "films": "film",
    "payments": "payment",
    "rentals": "rental",
    "stores": "store",
}
_OPERATORS = {
    "more than": ">",
    "greater than": ">",
    "above": ">",
    "over": ">",
    "less than": "<",
    "below": "<",
    "under": "<",
    "at least": ">=",
    "at most": "<=",
    "equal to": "=",
    "exactly": "=",
}
_ENTITIES = set(_BANK) | set(_PAGILA)
_RECORDS = {plural[:-1] + " records": plural for plural in _ENTITIES}
_NOUN = "|".join(sorted(_ENTITIES | _RECORDS.keys()))
_REQUEST = re.compile(
    r"(?:please )?(?:how many|count(?: all| the)?|"
    r"(?:what is|show(?: me)?) the (?:total )?number of) "
    r"(?P<entity>" + _NOUN + r")"
    r"(?: (?:are there|are recorded|in total))?"
    r"(?: (?:with (?:an? )?amount|where (?:the )?amount|have an amount|"
    r"whose amount)(?: is| of)? (?P<operator>" + "|".join(_OPERATORS) + r") "
    r"(?P<number>-?(?:0|[1-9][0-9]{0,14})(?:\.[0-9]{1,6})?)(?: (?P<unit>czk))?)?"
)


def scalar_count_sql(
    question: str, schema: Schema, selected: tuple[str, ...]
) -> str | None:
    if len(question) > 256 or not question.isascii():
        return None
    catalog = {BANK_TABLES: _BANK, PAGILA_TABLES: _PAGILA}.get(schema.allowed_tables)
    if catalog is None:
        return None
    text = " ".join(question.lower().split())
    match = _REQUEST.fullmatch(text[:-1] if text.endswith(("?", ".")) else text)
    if not match:
        return None
    table = catalog.get(_RECORDS.get(match["entity"], match["entity"]))
    if table is None or table not in selected:
        return None
    columns = {c.name: c for c in schema.tables[table].columns}
    if table + "_id" not in columns:
        return None
    # Every identifier comes from the fixed reviewed employee vocabulary above.
    sql = f'SELECT COUNT(*) AS record_count FROM "{table}"'
    if match["operator"] is None:
        return sql
    if table not in {"trans", "loan", "order", "payment"}:
        return None
    if match["unit"] and schema.allowed_tables != BANK_TABLES:
        return None
    amount = columns.get("amount")
    if amount is None or not re.fullmatch(
        r"(?:smallint|integer|bigint|numeric(?:\([0-9]+,\s*[0-9]+\))?)", amount.type
    ):
        return None
    predicate = f"amount {_OPERATORS[match['operator']]} {match['number']}"
    if amount.type.startswith("numeric"):
        # PostgreSQL sorts numeric NaN above all finite amounts. Special values
        # are not monetary amounts and must not satisfy an employee threshold.
        predicate += " AND amount NOT IN ('NaN', 'Infinity', '-Infinity')"
    return f"{sql} WHERE {predicate}"
